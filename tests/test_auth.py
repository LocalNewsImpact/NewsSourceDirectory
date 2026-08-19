"""Google sign-in must actually be restricted, not merely look restricted.

The `hd` parameter passed to Google is a hint to the account chooser. It changes
which accounts are offered and does not stop anyone completing the flow with a
personal account. Everything here exists because that distinction is easy to
miss and invisible when it is wrong.

No database: the adapter only reads the claims off the social login.
"""

from types import SimpleNamespace

import pytest
from allauth.core.exceptions import ImmediateHttpResponse

from directory.auth import DomainRestrictedAdapter

DOMAIN = "localnewsimpact.org"


def login_with(**extra_data):
    return SimpleNamespace(account=SimpleNamespace(extra_data=extra_data))


@pytest.fixture
def adapter(settings):
    settings.ALLOWED_GOOGLE_DOMAIN = DOMAIN
    return DomainRestrictedAdapter()


def test_a_verified_domain_account_is_admitted(adapter):
    adapter.pre_social_login(
        None,
        login_with(email=f"matt@{DOMAIN}", hd=DOMAIN, email_verified=True),
    )


@pytest.mark.parametrize(
    "claims,why",
    [
        (
            {"email": "someone@gmail.com", "hd": None, "email_verified": True},
            "a personal account with no hosted domain",
        ),
        (
            {"email": "someone@evil.test", "hd": "evil.test", "email_verified": True},
            "a different Workspace domain",
        ),
        (
            {"email": f"matt@{DOMAIN}", "hd": DOMAIN, "email_verified": False},
            "an unverified address claiming the domain",
        ),
        (
            {"email": "attacker@gmail.com", "hd": DOMAIN, "email_verified": True},
            "an hd claim that disagrees with the address",
        ),
        ({}, "no claims at all"),
    ],
)
def test_everything_else_is_refused(adapter, claims, why):
    with pytest.raises(ImmediateHttpResponse):
        adapter.pre_social_login(None, login_with(**claims))


def test_an_empty_setting_disables_the_restriction(settings):
    """The portal service runs the same code with no domain configured, and must
    not reject the outside accounts it exists to serve."""
    settings.ALLOWED_GOOGLE_DOMAIN = ""
    DomainRestrictedAdapter().pre_social_login(
        None, login_with(email="researcher@example.edu", email_verified=True)
    )


def test_case_is_not_a_way_around_it(adapter):
    adapter.pre_social_login(
        None,
        login_with(email=f"Matt@{DOMAIN.upper()}", hd=DOMAIN, email_verified=True),
    )
