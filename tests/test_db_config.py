"""How the database connection is chosen.

Cloud Run reaches Cloud SQL over a unix socket, not a host and port. A
DATABASE_URL written for a laptop points a deployed service at its own
localhost — which is exactly what the first real deploy did.
"""

from config.db import database_config


class TestExplicitUrl:
    def test_database_url_wins(self):
        config = database_config({"DATABASE_URL": "postgres://u:p@db.example:5432/name"})
        assert config["HOST"] == "db.example"
        assert config["NAME"] == "name"

    def test_an_empty_url_is_not_a_url(self):
        """An unset variable often arrives as an empty string, and treating that
        as a valid DSN produces a confusing failure much later."""
        config = database_config({"DATABASE_URL": "   "})
        assert config["HOST"] == "localhost"


class TestCloudRun:
    ENV = {
        "CLOUD_SQL_CONNECTION_NAME": "mizzou-news-crawler:us-central1:mizzou-db-prod",
        "DB_PASSWORD": "secret",
    }

    def test_connects_over_a_socket_not_a_host(self):
        config = database_config(self.ENV)
        assert config["HOST"] == "/cloudsql/mizzou-news-crawler:us-central1:mizzou-db-prod"
        assert config["PORT"] == ""

    def test_uses_the_directory_database_and_role_by_default(self):
        config = database_config(self.ENV)
        assert config["NAME"] == "directory"
        assert config["USER"] == "directory"

    def test_password_comes_from_the_environment(self):
        assert database_config(self.ENV)["PASSWORD"] == "secret"

    def test_names_can_be_overridden(self):
        config = database_config({**self.ENV, "DB_NAME": "other", "DB_USER": "someone"})
        assert config["NAME"] == "other"
        assert config["USER"] == "someone"

    def test_an_explicit_url_still_takes_precedence(self):
        """So a one-off job can point somewhere else without editing settings."""
        config = database_config({**self.ENV, "DATABASE_URL": "postgres://u:p@elsewhere:5432/x"})
        assert config["HOST"] == "elsewhere"


class TestFallback:
    def test_an_empty_environment_gets_the_local_database(self):
        config = database_config({})
        assert config["HOST"] == "localhost"
        assert config["PORT"] == 5434

    def test_the_fallback_is_never_a_socket(self):
        """A missing connection name must not silently produce '/cloudsql/'."""
        assert not str(database_config({}).get("HOST", "")).startswith("/cloudsql")
        assert not str(database_config({"CLOUD_SQL_CONNECTION_NAME": ""}).get("HOST")).startswith(
            "/cloudsql"
        )
