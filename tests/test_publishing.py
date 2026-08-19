"""Requesting a publish from the admin.

The admin only asks; the workflow does the reading, through a role that holds
SELECT and nothing else. These tests pin that the request is well-formed and
that failures are reported rather than swallowed — a button that silently does
nothing is worse than no button.
"""

import json
from unittest.mock import patch

import pytest

from directory.publishing import PublishError, request_publish


class FakeResponse:
    def __init__(self, status=204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestRequestPublish:
    def test_it_posts_the_event_the_workflow_listens_for(self, monkeypatch):
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "t0ken")
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            captured["auth"] = request.headers.get("Authorization")
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            request_publish(reason="admin:someone")

        assert captured["url"].endswith("/dispatches")
        # Must match the workflow's `types:` or nothing happens and nothing says so.
        assert captured["body"]["event_type"] == "publish-feed"
        assert captured["body"]["client_payload"]["reason"] == "admin:someone"
        assert captured["auth"] == "Bearer t0ken"

    def test_no_token_is_a_clear_refusal(self, monkeypatch):
        """Not a silent no-op: the editor needs to know nothing was requested."""
        monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
        with pytest.raises(PublishError, match="No GITHUB_DISPATCH_TOKEN"):
            request_publish()

    def test_a_rejection_is_surfaced(self, monkeypatch):
        import urllib.error

        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "bad")

        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

        with (
            patch("urllib.request.urlopen", fake_urlopen),
            pytest.raises(PublishError, match="403"),
        ):
            request_publish()

    def test_an_unreachable_github_is_surfaced(self, monkeypatch):
        import urllib.error

        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "t0ken")

        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError("no route to host")

        with patch("urllib.request.urlopen", fake_urlopen), pytest.raises(PublishError):
            request_publish()

    def test_the_repository_can_be_overridden(self, monkeypatch):
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPO", "someone/elsewhere")
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            request_publish()
        assert "someone/elsewhere" in seen["url"]


@pytest.mark.integration
@pytest.mark.django_db
class TestAdminAction:
    def test_a_failure_is_reported_to_the_editor(self, monkeypatch):
        """The action must not report success it cannot verify."""
        from django.contrib.admin.sites import AdminSite

        from directory.admin import OutletAdmin
        from directory.models import Outlet

        monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
        admin_obj = OutletAdmin(Outlet, AdminSite())
        messages = []
        admin_obj.message_user = lambda request, msg, level=None: messages.append((msg, level))

        admin_obj.publish_feed(_FakeRequest(), Outlet.objects.none())

        assert messages and "GITHUB_DISPATCH_TOKEN" in messages[0][0]


class _FakeRequest:
    def get_username(self):
        return "tester"

    @property
    def user(self):
        return self
