"""Who owns which tables when the suite shares one database.

Datadesk owns the suite's identity: users, sessions, permissions and the
allauth records beside them. The directory reads and writes those tables
but must never create or alter them — with `search_path=directory,public`
a `CREATE TABLE auth_user` here would build `directory.auth_user`,
shadowing the shared one, and the two consoles would quietly authenticate
different people.

So the directory's migrations stop at its own tables. Datadesk's do the
rest, and a Django upgrade that adds an auth migration is applied there.

Off by default. Running against its own database — locally, and in CI —
the directory owns everything and migrates everything, exactly as before.
"""

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
    """Refuse to migrate what another application owns."""

    def allow_migrate(self, db, app_label, **hints):
        if app_label in SHARED_IDENTITY_APPS:
            return False
        return None
