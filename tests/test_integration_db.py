"""Integration tests: these need a live Postgres.

    make test

starts one. The marker is what lets `pytest -m "not integration"` run the
rest of the suite before Docker is working; the floor is judged on the
whole suite, which is what `make test` and CI run.
"""

import os

import pytest

pytestmark = pytest.mark.integration

psycopg = pytest.importorskip("psycopg", reason="pip install -r requirements-dev.txt")

DSN = os.environ.get("DATABASE_URL", "postgres://directory:directory@localhost:5434/directory")


@pytest.fixture(scope="module")
def conn():
    try:
        with psycopg.connect(DSN, connect_timeout=5) as c:
            yield c
    except psycopg.OperationalError as exc:
        pytest.fail(f"no Postgres at {DSN} — run 'make db-up'.\n{exc}")


def test_database_is_reachable(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


def test_server_is_postgres_16_or_newer(conn):
    """The schema uses generated columns and modern index types."""
    assert conn.info.server_version >= 160000


def test_can_create_and_drop_a_table(conn):
    """Proves the connected role owns its schema, which migrations will need."""
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS _probe (id int primary key, note text)")
        cur.execute("INSERT INTO _probe VALUES (1, 'hello') ON CONFLICT DO NOTHING")
        cur.execute("SELECT note FROM _probe WHERE id = 1")
        assert cur.fetchone()[0] == "hello"
        cur.execute("DROP TABLE _probe")
    conn.rollback()


def test_utf8_round_trips(conn):
    """Outlet names carry accents and curly quotes; a Latin-1 database mangles them."""
    with conn.cursor() as cur:
        cur.execute("SELECT %s::text", ["Assessing Oregon's Ecosystem — Ñ"])
        assert cur.fetchone()[0] == "Assessing Oregon's Ecosystem — Ñ"
