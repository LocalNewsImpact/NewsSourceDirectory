"""Choosing a database connection.

Three environments, three shapes, and the differences are not cosmetic:

  local / CI     DATABASE_URL over TCP
  Cloud Run      a unix socket at /cloudsql/<connection name>
  fallback       the local development database

Cloud Run reaches Cloud SQL through a socket, not a host and port, so a
DATABASE_URL written for a laptop silently points a deployed service at its own
localhost. Assembling the connection from parts keeps the password out of any
URL and makes the socket case explicit rather than something to remember.
"""

from __future__ import annotations

from collections.abc import Mapping

LOCAL_DEFAULT = "postgres://directory:directory@localhost:5434/directory"


def _options(env: Mapping[str, str]) -> dict:
    """Connection options, which is where the schema lives.

    When the directory shares Datadesk's database its own tables sit in a
    `directory` schema and the suite's identity tables stay in `public`,
    so the search path has to name both: unqualified table names resolve
    to the directory's own first and fall through to the shared ones.
    Unset, the connection behaves as it always did and everything is in
    `public`.
    """
    search_path = env.get("DB_SEARCH_PATH", "").strip()
    return {"options": f"-c search_path={search_path}"} if search_path else {}


def database_config(env: Mapping[str, str]) -> dict:
    """Return Django DATABASES['default'] for the given environment."""
    import dj_database_url

    url = env.get("DATABASE_URL", "").strip()
    if url:
        config = dj_database_url.parse(url, conn_max_age=600, conn_health_checks=True)
        options = _options(env)
        if options:
            config.setdefault("OPTIONS", {}).update(options)
        return config

    connection_name = env.get("CLOUD_SQL_CONNECTION_NAME", "").strip()
    if connection_name:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env.get("DB_NAME", "directory"),
            "USER": env.get("DB_USER", "directory"),
            "PASSWORD": env.get("DB_PASSWORD", ""),
            # Not a hostname. psycopg treats a leading slash as a socket
            # directory, which is how Cloud Run exposes Cloud SQL.
            "HOST": f"/cloudsql/{connection_name}",
            "PORT": "",
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": _options(env),
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "TIME_ZONE": None,
            "TEST": {},
        }

    return dj_database_url.parse(LOCAL_DEFAULT, conn_max_age=600, conn_health_checks=True)
