"""Sharing Datadesk's database, and the boundaries that keeps.

The directory's own tables live in a `directory` schema; the suite's
identity — users, sessions, permissions, allauth — stays in `public` and
belongs to Datadesk. What these pin down is the line between the two,
because crossing it fails silently: a `CREATE TABLE auth_user` under
`search_path=directory,public` builds a second, shadowing user table and
the two consoles start authenticating different people.

All of it is off unless the deployment turns it on, so running against
its own database is unchanged.
"""

from config.db import database_config
from config.routers import SHARED_IDENTITY_APPS, IdentityOwnedByDatadesk

CLOUD_SQL = {
    "CLOUD_SQL_CONNECTION_NAME": "p:us-central1:i",
    "DB_NAME": "datadesk",
    "DB_USER": "directory",
    "DB_PASSWORD": "x",
}


# --- where the tables are looked for ----------------------------------------


def test_the_search_path_names_the_directory_first_then_the_shared_tables():
    config = database_config({**CLOUD_SQL, "DB_SEARCH_PATH": "directory,public"})
    assert config["OPTIONS"]["options"] == "-c search_path=directory,public"
    assert config["NAME"] == "datadesk"


def test_a_connection_with_no_search_path_is_unchanged():
    """Its own database, everything in public — how it has always run
    locally and in CI."""
    config = database_config(CLOUD_SQL)
    assert config["OPTIONS"] == {}


def test_a_database_url_takes_the_search_path_too():
    config = database_config(
        {
            "DATABASE_URL": "postgres://u:p@h:5432/datadesk",
            "DB_SEARCH_PATH": "directory,public",
        }
    )
    assert config["OPTIONS"]["options"] == "-c search_path=directory,public"


# --- what this application may create ---------------------------------------


def test_the_directory_never_migrates_the_shared_identity_tables():
    """Datadesk owns them. Building them here would shadow the real ones
    under the search path rather than fail, which is why this is a rule
    and not a convention."""
    router = IdentityOwnedByDatadesk()
    for app_label in SHARED_IDENTITY_APPS:
        assert router.allow_migrate("default", app_label) is False


def test_the_directory_still_migrates_its_own():
    router = IdentityOwnedByDatadesk()
    assert router.allow_migrate("default", "directory") is None


def test_auth_is_among_the_apps_it_refuses():
    """Named explicitly: allauth's tables reference auth_user, so missing
    any one of these leaves a table pointing at the wrong user table."""
    assert {"auth", "sessions", "account", "socialaccount"} <= SHARED_IDENTITY_APPS


# --- the cookie that carries the session ------------------------------------


def test_the_cookie_names_match_datadesks():
    """A mismatch is not an error, it is two sessions: each console sets
    its own cookie, reads past the other's, and signs the person in
    again — which is the whole thing this was meant to stop."""
    from django.conf import settings

    assert settings.SESSION_COOKIE_NAME == "lnic_session"
    assert settings.CSRF_COOKIE_NAME == "lnic_csrf"


def test_csrf_is_scoped_wherever_the_session_is():
    from django.conf import settings

    assert settings.CSRF_COOKIE_DOMAIN == settings.SESSION_COOKIE_DOMAIN


def test_sharing_is_off_unless_the_deployment_says_otherwise():
    import os

    from django.conf import settings

    if not os.environ.get("SHARED_IDENTITY"):
        assert settings.SHARED_IDENTITY is False
        assert not hasattr(settings, "DATABASE_ROUTERS") or settings.DATABASE_ROUTERS == []
