"""Datadesk owns identity; this service borrows it.

Both run against one database on one Cloud SQL instance. Datadesk keeps
the user, session and allauth tables in `public`; this package keeps its
own in a `directory` schema and reads across.

A router used to sit here refusing migrations for the shared apps, because
with `search_path=directory,public` an unqualified `CREATE TABLE` lands in
`directory` — a migration that touched `auth` would have built a second
`auth_user` shadowing the shared one, and this console would authenticate
against a different set of people than Datadesk with nothing erroring.

Nothing in this repository migrates any more. Datadesk's deploy runs
`manage.py migrate directory`, which names the app and so cannot reach
another one's tables. What remains here is what a local checkout still
needs: the search path that finds the schema, and the cookie and site-row
settings that have to agree with Datadesk's.
"""

from config.db import database_config

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


def test_no_router_stands_between_this_package_and_the_database():
    """The router was scaffolding for a second process migrating the same
    database. There is no second process: Datadesk migrates, naming the
    app. A router reintroduced here would silently change what a local
    checkout can write."""
    from django.conf import settings

    assert getattr(settings, "DATABASE_ROUTERS", []) == []


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


# --- who reaches this console's admin ---------------------------------------
#
# No database. The gate is a pure function of a user object, and these run
# in the unit job, which has no Postgres -- creating rows here passed
# locally against a stray container and failed in CI on a refused
# connection.


class _User:
    """Enough of a user for a gate to decide about."""

    def __init__(self, username="x", is_staff=False, is_active=True):
        self.username = username
        self.is_staff = is_staff
        self.is_active = is_active


def only_dana(user):
    """Stands in for Datadesk's grant check."""
    return user.username == "dana"


def test_the_admin_gate_falls_back_to_is_staff(settings):
    """Standalone, there is no grant model to ask, so `is_staff` is the
    right answer rather than a failure."""
    from directory.views import may_reach_admin

    settings.DIRECTORY_ADMIN_GATE = ""
    assert may_reach_admin(_User(is_staff=True))
    assert not may_reach_admin(_User())


def test_a_configured_gate_replaces_is_staff(settings):
    """Datadesk points this at its grant check, so somebody without
    `is_staff` reaches the admin and somebody with it does not. Deriving
    `is_staff` from a grant would leave two things to keep in step;
    replacing the question leaves one."""
    from directory.views import may_reach_admin

    settings.DIRECTORY_ADMIN_GATE = "tests.test_shared_identity.only_dana"
    assert may_reach_admin(_User("dana"))
    assert not may_reach_admin(_User("t", is_staff=True))


def test_the_admin_site_asks_the_same_gate(settings, rf):
    """The gateway only decides where to send somebody not signed in.
    Django checks `has_permission` on every admin view, so leaving that
    on `is_staff` would let the two disagree."""
    from django.contrib import admin

    settings.DIRECTORY_ADMIN_GATE = "tests.test_shared_identity.only_dana"

    request = rf.get("/admin/")
    request.user = _User("dana")
    assert admin.site.has_permission(request)

    request.user = _User("t", is_staff=True)
    assert not admin.site.has_permission(request)


def test_an_inactive_account_is_refused_whatever_the_gate_says(settings, rf):
    """Django's own check is `is_active and is_staff`; replacing the
    second half must not drop the first."""
    from django.contrib import admin

    settings.DIRECTORY_ADMIN_GATE = "tests.test_shared_identity.only_dana"
    request = rf.get("/admin/")
    request.user = _User("dana", is_active=False)
    assert not admin.site.has_permission(request)
