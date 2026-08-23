"""Who owns which tables when the suite shares one database.

Datadesk owns identity. This service reads the same `auth_user`,
`django_session` and allauth tables out of the `public` schema, and keeps
its own tables in `directory`.

The hazard this guards is narrow and easy to trip. With
`search_path=directory,public`, an unqualified `CREATE TABLE` lands in
`directory` — the first schema on the path. So a `migrate` here that
touched `auth` would create a *second* `auth_user` inside `directory`,
shadowing the shared one, and this service would quietly authenticate
against a different set of people than Datadesk. Altering the shared
tables is Datadesk's job; this refuses to try.

Only when identity is actually shared. Running against its own database
— locally, in CI — this service still owns everything and must migrate
it all, or it has no user table at all.
"""

# Every app whose tables live in the shared schema and belong to Datadesk.
SHARED_IDENTITY_APPS = frozenset(
    {
        "auth",
        "contenttypes",
        "sessions",
        "admin",
        "sites",
        "account",
        "socialaccount",
    }
)


class IdentityOwnedByDatadesk:
    """Refuse to migrate what this service does not own.

    Reads and writes are unaffected — the grants in the database decide
    those, and this service is allowed both on the identity tables. Only
    schema changes are refused.
    """

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in SHARED_IDENTITY_APPS:
            return False
        return None
