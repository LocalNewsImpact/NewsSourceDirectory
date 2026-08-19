"""The health endpoint the deploy smoke test depends on.

It lives at /_health because Google's front end intercepts /healthz on Cloud Run
and returns its own 404 without forwarding the request.
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_healthz_reports_ok(client):
    response = client.get("/_health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_healthz_fails_when_the_database_is_unreachable(client, monkeypatch):
    """A service answering 200 while unable to read anything is worse than one
    that admits it is down — the deploy would go green on a broken revision."""
    from django.db import connection

    def explode():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(connection, "cursor", explode)
    response = client.get("/_health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_the_root_leads_to_the_admin(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/"
