"""Google sign-in restricted to one Workspace domain.

The `hd` parameter in SOCIALACCOUNT_PROVIDERS is a hint to Google's account
chooser. It changes which accounts are offered and does not prevent anyone
completing the flow with a personal account. The claim has to be checked here,
or the login screen only looks restricted.
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden


class DomainRestrictedAdapter(DefaultSocialAccountAdapter):
    """Admit only verified addresses in the configured hosted domain."""

    def pre_social_login(self, request, sociallogin):
        allowed = getattr(settings, "ALLOWED_GOOGLE_DOMAIN", "")
        if not allowed:
            return

        extra = sociallogin.account.extra_data or {}
        email = (extra.get("email") or "").lower()

        # Both halves matter. `hd` establishes the domain; email_verified stops
        # an unverified address from claiming one.
        domain_ok = extra.get("hd") == allowed
        verified = bool(extra.get("email_verified"))

        if not (domain_ok and verified and email.endswith(f"@{allowed}")):
            raise ImmediateHttpResponse(
                HttpResponseForbidden(f"This application is restricted to {allowed} accounts.")
            )

    def is_open_for_signup(self, request, sociallogin):
        return True


class NoPublicSignupAdapter(DefaultAccountAdapter):
    """Password signup is closed; accounts arrive via Google or a superuser."""

    def is_open_for_signup(self, request):
        return False

    def clean_password(self, password, user=None):
        raise PermissionDenied("Password accounts are not created here.")
