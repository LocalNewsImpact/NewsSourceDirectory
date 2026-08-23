"""Datadesk owns identity; this service borrows it.

Both run against one database on one Cloud SQL instance. Datadesk keeps
the user, session and allauth tables in `public`; this service keeps its
own in a `directory` schema and reads across.

The failure these guard against is quiet rather than loud. With
`search_path=directory,public` an unqualified `CREATE TABLE` lands in
`directory`, so a migration here that touched `auth` would build a
second `auth_user` shadowing the shared one — and this console would
authenticate against a different set of people than Datadesk, with
nothing erroring.
"""

import pytest

from config.db import database_config
from config.routers import SHARED_IDENTITY_APPS, IdentityOwnedByDatadesk

# --- the connection ---------------------------------------------------------


def test_the_schema_search_path_names_both():
    """Its own tables first, the shared ones behind them: unqualified
    names resolve to the directory's own and fall through to identity."""
    config = database_config(
        {
            "CLOUD_SQL_CONNECTION_NAME": "p:r:i",
            "DB_NAME": "datadesk",
            "DB_SEARCH_PATH": "directory,public",
        }
    )
    assert config["OPTIONS"]["options"] == "-c search_path=directory,public"
    assert config["NAME"] == "datadesk"


def test_without_a_search_path_the_connection_is_unchanged():
    """Local development and CI run against this service's own database,
    where everything is in `public` and nothing is shared."""
    config = database_config({"CLOUD_SQL_CONNECTION_NAME": "p:r:i", "DB_NAME": "directory"})
    assert config["OPTIONS"] == {}


def test_a_database_url_can_carry_the_search_path_too():
    config = database_config(
        {
            "DATABASE_URL": "postgres://u:p@h:5432/datadesk",
            "DB_SEARCH_PATH": "directory,public",
        }
    )
    assert config["OPTIONS"]["options"] == "-c search_path=directory,public"


# --- who may change what ----------------------------------------------------


@pytest.mark.parametrize("app_label", sorted(SHARED_IDENTITY_APPS))
def test_this_service_never_migrates_a_shared_app(app_label):
    """Not "does not need to" — must not. Creating auth_user here would
    shadow the shared one and split the two consoles' idea of who is
    signed in."""
    assert IdentityOwnedByDatadesk().allow_migrate("default", app_label) is False


@pytest.mark.parametrize("app_label", ["directory", "checks", "feed"])
def test_this_service_still_migrates_its_own(app_label):
    assert IdentityOwnedByDatadesk().allow_migrate("default", app_label) is None


def test_the_shared_set_is_every_app_whose_tables_are_datadesks():
    """Named explicitly rather than inferred, so adding an app that
    writes to `public` is a decision someone makes on purpose."""
    assert {
        "auth",
        "contenttypes",
        "sessions",
        "admin",
        "sites",
        "account",
        "socialaccount",
    } == SHARED_IDENTITY_APPS


def test_reads_and_writes_are_not_the_routers_business():
    """Only schema changes are refused. Whether this service may read
    auth_user or write a session is decided by the database grants, and
    it is allowed both."""
    router = IdentityOwnedByDatadesk()
    assert not hasattr(router, "db_for_read")
    assert not hasattr(router, "db_for_write")


# --- the cookie -------------------------------------------------------------


def test_the_cookie_names_match_datadesks():
    """One cookie read by two applications cannot be called two things."""
    from django.conf import settings

    assert settings.SESSION_COOKIE_NAME == "lnic_session"
    assert settings.CSRF_COOKIE_NAME == "lnic_csrf"


def test_csrf_is_scoped_wherever_the_session_is():
    """A session shared across subdomains and a CSRF cookie that is not
    fails every POST made from the other console."""
    from django.conf import settings

    assert settings.CSRF_COOKIE_DOMAIN == settings.SESSION_COOKIE_DOMAIN


def test_sharing_is_off_unless_asked_for():
    """The default has to be a service that owns its own database, or a
    fresh checkout tries to borrow tables that are not there."""
    from django.conf import settings

    assert settings.SHARED_IDENTITY is False
    assert not hasattr(settings, "DATABASE_ROUTERS") or settings.DATABASE_ROUTERS == []


# --- the shared site table --------------------------------------------------


def test_this_service_can_take_its_own_site_row():
    """django_site is shared with Datadesk and a row cannot be. Both
    applications shipped SITE_ID = 1, so whichever deployed last owned
    the row and the other console's site quietly became theirs. Datadesk
    keeps 1; this takes 2 in the shared database."""
    import importlib
    import os

    os.environ["SITE_ID"] = "2"
    try:
        module = importlib.reload(importlib.import_module("config.settings"))
        assert module.SITE_ID == 2
    finally:
        del os.environ["SITE_ID"]
        importlib.reload(importlib.import_module("config.settings"))


def test_a_checkout_on_its_own_database_still_uses_the_first_row():
    """One database, one site row, nothing to collide with."""
    from django.conf import settings

    assert settings.SITE_ID == 1


def test_configure_site_writes_whichever_row_is_ours():
    """The command already targets settings.SITE_ID rather than a
    hardcoded 1, which is what makes moving to row 2 a setting and not a
    code change."""
    import inspect

    from directory.management.commands.configure_site import Command

    source = inspect.getsource(Command.handle)
    assert "settings.SITE_ID" in source
    assert "pk=1" not in source
