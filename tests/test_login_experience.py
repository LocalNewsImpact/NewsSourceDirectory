"""Where each kind of visitor ends up when they try to reach the admin.

The loop this pins down was real: an authenticated user without staff rights
bounced between /admin/ and the login page indefinitely, because Django sends
non-staff to the admin login, the admin login redirected to allauth, and allauth
sends an already-authenticated user back to the admin.
"""

import pytest
from django.contrib.auth import get_user_model

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def staff():
    return get_user_model().objects.create_user(
        username="staff@localnewsimpact.org",
        email="staff@localnewsimpact.org",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def outsider():
    return get_user_model().objects.create_user(
        username="nobody@localnewsimpact.org", email="nobody@localnewsimpact.org", password="x"
    )


class TestAdminLoginGateway:
    """Tested as a view rather than through the URL map, because the route is
    only installed when Google sign-in is configured — and the logic it guards
    is exactly what must not regress."""

    @staticmethod
    def call(user=None, **params):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from directory.views import admin_login_gateway

        request = RequestFactory().get("/admin/login/", params)
        request.user = user or AnonymousUser()
        return admin_login_gateway(request)

    def test_an_anonymous_visitor_is_sent_somewhere_they_can_sign_in(self):
        response = self.call()
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/accounts/login/")

    def test_the_destination_is_carried_through(self):
        response = self.call(next="/admin/directory/outlet/")
        assert "next=/admin/directory/outlet/" in response.headers["Location"]

    def test_a_signed_in_user_without_access_is_told_so(self, outsider):
        """Not redirected. Redirecting them is precisely what created the loop:
        Django sends non-staff to the admin login, that sent them to allauth,
        and allauth sends an authenticated user back to the admin."""
        response = self.call(outsider)
        assert response.status_code == 403
        assert b"not authorised" in response.content

    def test_the_message_says_which_account_is_signed_in(self, outsider):
        """Otherwise someone signed in with the wrong Google account has no way
        to tell why they are being refused."""
        content = self.call(outsider).content
        assert outsider.email.encode() in content

    def test_a_staff_member_is_let_through(self, staff):
        response = self.call(staff, next="/admin/")
        assert response.status_code == 302
        assert response.headers["Location"] == "/admin/"

    def test_nobody_is_ever_redirected_back_to_this_page(self, outsider, staff):
        """The loop invariant: this view must never send anyone to /admin/login/."""
        for user in (None, outsider, staff):
            response = self.call(user)
            location = response.headers.get("Location", "")
            assert "/admin/login" not in location


class TestSignInPage:
    def test_it_names_the_domain_that_will_work(self, client):
        response = client.get("/accounts/login/")
        assert response.status_code == 200
        assert b"localnewsimpact.org" in response.content

    def test_it_is_styled_rather_than_raw(self, client):
        """It is the front door; an unstyled default reads as broken."""
        response = client.get("/accounts/login/")
        assert b"News Source Directory" in response.content
        assert b"auth-card" in response.content

    def test_it_wears_the_console_theme(self, client):
        """The backend is reached from Datadesk's navigation, so it looks
        like Datadesk. The stylesheets are linked from that service rather
        than copied here: the tokens are one file in one repository, and a
        second copy is how two consoles drift into designs that nearly
        agree.

        The public directory widget is the other half of this decision and
        goes the other way — it matches localnewsimpact.org, and nothing
        here should change that.
        """
        content = client.get("/accounts/login/").content
        for sheet in (b"tokens.css", b"auth.css", b"fonts.css"):
            assert sheet in content, sheet
        assert b"datadesk.localnewsimpact.org" in content

    def test_it_offers_the_way_back_to_the_other_console(self, client):
        """Arriving from Datadesk's Sources group, a reader should be able
        to get back without the browser's history."""
        content = client.get("/accounts/login/").content
        assert b"https://datadesk.localnewsimpact.org/" in content

    def test_there_is_no_invitation_to_sign_up(self, client):
        """allauth's default offers self-service signup. Accounts here are
        created by an administrator, so that link leads nowhere useful."""
        content = client.get("/accounts/login/").content.lower()
        assert b"sign up" not in content

    def test_the_signup_url_explains_itself(self, client):
        """allauth links to it from its own pages, so it must say why rather
        than presenting a form that cannot work."""
        response = client.get("/accounts/signup/")
        assert b"created by an administrator" in response.content


class TestArrivingFromDatadesk:
    """Datadesk's navigation links straight here, so an unauthenticated
    arrival should be a redirect nobody has to act on rather than a form to
    fill in — Google already holds the session.

    Tested as a view for the same reason as the class above: the route
    exists only when Google sign-in is configured.
    """

    def test_the_handshake_starts_without_a_page_in_between(self, settings):
        settings.LOGIN_URL = "/accounts/google/login/"
        response = TestAdminLoginGateway.call()
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/accounts/google/login/")

    def test_where_they_were_going_survives_it(self, settings):
        settings.LOGIN_URL = "/accounts/google/login/"
        response = TestAdminLoginGateway.call(next="/admin/directory/outlet/")
        assert "next=/admin/directory/outlet/" in response.headers["Location"]

    def test_without_google_it_is_still_the_sign_in_page(self, settings):
        """Blanking the client secret has to bring the ordinary form back,
        or a broken OAuth client locks everybody out."""
        settings.LOGIN_URL = "/accounts/login/"
        response = TestAdminLoginGateway.call()
        assert response.headers["Location"].startswith("/accounts/login/")

    def test_the_sign_in_page_remains_reachable(self, client):
        """Auto-starting the handshake must not remove the way to sign in as
        somebody else."""
        assert client.get("/accounts/login/").status_code == 200
