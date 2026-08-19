"""Optional dependencies that only fail in production.

Two outages came from the same shape of gap: django-allauth's Google provider
imports packages that django-allauth itself does not depend on. Missing
`requests` crashed the container on boot; missing `jwt` let sign-in get all the
way to Google and back before failing with a 500 on the callback.

Neither showed up in any other test, because nothing else imports them. These do.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module,why",
    [
        ("requests", "allauth's Google provider imports it at module level"),
        ("jwt", "verifying the Google ID token signature"),
        ("cryptography", "PyJWT needs it for RS256, which Google uses"),
    ],
)
def test_optional_dependency_is_installed(module, why):
    importlib.import_module(module)


def test_pyjwt_can_actually_verify_rs256():
    """PyJWT installs without cryptography and then fails only at signature
    verification — exactly where the user is mid-login."""
    import jwt

    assert "RS256" in jwt.algorithms.get_default_algorithms()


def test_the_google_provider_imports():
    """The whole chain, in one line: if this fails, sign-in is broken."""
    importlib.import_module("allauth.socialaccount.providers.google.views")
