"""How Google sign-in is configured, and how it fails when it is not.

Both of the bugs pinned here produced the same unhelpful symptom in production:
allauth's "Third-Party Login Failure" page, with a 401 on the callback and
nothing in the logs saying why.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class TestSiteDomain:
    """Django ships Site 1 as example.com, and allauth builds OAuth callback
    URLs from it — so a fresh database asks Google to redirect to example.com."""

    def test_the_default_site_is_replaced(self):
        from django.contrib.sites.models import Site

        call_command("configure_site", domain="sources.localnewsimpact.org", verbosity=0)
        assert Site.objects.get(pk=1).domain == "sources.localnewsimpact.org"

    def test_rerunning_changes_nothing(self):
        from django.contrib.sites.models import Site

        call_command("configure_site", domain="example.org", verbosity=0)
        call_command("configure_site", domain="example.org", verbosity=0)
        assert Site.objects.filter(domain="example.org").count() == 1

    @pytest.mark.parametrize("domain", ["", "*", "example.com"])
    def test_a_placeholder_domain_is_refused(self, domain, settings):
        """Accepting one would recreate the bug this command exists to fix."""
        settings.ALLOWED_HOSTS = ["*"]
        with pytest.raises(CommandError):
            call_command("configure_site", domain=domain, verbosity=0)

    def test_the_domain_is_inferred_from_allowed_hosts(self, settings):
        from django.contrib.sites.models import Site

        settings.ALLOWED_HOSTS = ["sources.localnewsimpact.org", ".run.app"]
        call_command("configure_site", verbosity=0)
        assert Site.objects.get(pk=1).domain == "sources.localnewsimpact.org"

    def test_wildcards_are_skipped_when_inferring(self, settings):
        """'.run.app' is not a hostname anyone types or that Google redirects to."""
        settings.ALLOWED_HOSTS = [".run.app", "sources.localnewsimpact.org"]
        call_command("configure_site", verbosity=0)
        from django.contrib.sites.models import Site

        assert Site.objects.get(pk=1).domain == "sources.localnewsimpact.org"


class TestProviderConfiguration:
    def test_no_app_is_declared_without_credentials(self):
        """An APP with empty credentials is worse than none: allauth uses it,
        the token exchange fails, and the error says nothing useful."""
        from config import settings as module

        config = module.build_socialaccount_providers("", "", "localnewsimpact.org")
        assert "APP" not in config["google"]

    def test_an_app_is_declared_when_both_are_present(self):
        from config import settings as module

        config = module.build_socialaccount_providers("id-123", "secret-456", "example.org")
        assert config["google"]["APP"]["client_id"] == "id-123"
        assert config["google"]["APP"]["secret"] == "secret-456"

    def test_half_configured_counts_as_unconfigured(self):
        from config import settings as module

        assert "APP" not in module.build_socialaccount_providers("id-only", "", "x.org")["google"]
        assert (
            "APP" not in module.build_socialaccount_providers("", "secret-only", "x.org")["google"]
        )

    def test_the_hosted_domain_hint_is_always_sent(self):
        """It does not enforce anything — the adapter does that — but it keeps
        the account chooser from offering personal accounts."""
        from config import settings as module

        config = module.build_socialaccount_providers("id", "secret", "localnewsimpact.org")
        assert config["google"]["AUTH_PARAMS"]["hd"] == "localnewsimpact.org"


class TestAdminLoginRouting:
    """Django's admin form has no Google button, so leaving /admin/login/ in
    place is a password box with no valid password behind it."""

    def test_the_admin_login_redirects_when_google_is_configured(self, client, settings):
        if not settings.GOOGLE_SIGN_IN_CONFIGURED:
            pytest.skip("provider unconfigured locally; the redirect is not installed")
        response = client.get("/admin/login/")
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/accounts/login/")

    def test_the_password_form_remains_when_it_is_not(self, client, settings):
        """The escape hatch: blank the client id and the ordinary form returns,
        so a broken OAuth client cannot lock everyone out."""
        if settings.GOOGLE_SIGN_IN_CONFIGURED:
            pytest.skip("provider configured; the form is deliberately bypassed")
        assert client.get("/admin/login/").status_code == 200

    def test_login_required_sends_people_somewhere_usable(self, settings):
        assert settings.LOGIN_URL == "/accounts/login/"
