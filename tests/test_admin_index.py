"""The admin index shows the dashboard *and* the models.

This template replaces Django's own `admin/index.html`, so `block.super`
here resolves to `admin/base.html`, whose content block renders an empty
`{{ content }}` for this view — not the app list. Relying on it left the
index with no models on it at all, reachable only through the sidebar.

The app list matters more as the suite grows: once this app is installed
alongside others in one process, a single admin carries every model from
every application, and an index that renders only this app's dashboard
hides all of them.
"""

import pytest
from django.conf import settings
from django.template.loader import get_template

APP_LIST = [
    {
        "name": "Audit",
        "app_label": "audit",
        "app_url": "/admin/audit/",
        "has_module_perms": True,
        "models": [
            {
                "name": "Audit log entries",
                "object_name": "AuditLogEntry",
                "admin_url": "/admin/audit/auditlogentry/",
                "perms": {"change": True},
                "view_only": False,
            }
        ],
    }
]


@pytest.fixture
def rendered(settings_plain_static):
    return get_template("admin/index.html").render(
        {
            "app_list": APP_LIST,
            "review_tiles": [],
            "quality_tiles": [],
            "registry_tiles": [],
            "unserved": None,
        }
    )


@pytest.fixture
def settings_plain_static(monkeypatch):
    """The manifest backend needs a collectstatic run; this template test
    does not."""
    monkeypatch.setattr(
        settings,
        "STORAGES",
        {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        },
    )


def test_the_models_are_on_the_index(rendered):
    """The regression: an index that lists no models at all."""
    assert "Audit log entries" in rendered
    assert "/admin/audit/auditlogentry/" in rendered


def test_the_dashboard_is_still_there(rendered):
    assert "Needs attention" in rendered


def test_the_dashboard_comes_first(rendered):
    """A summary is worth reading before a list of tables."""
    assert rendered.index("Needs attention") < rendered.index("Audit log entries")


def test_it_does_not_rely_on_block_super_for_the_list():
    """Naming the failure so it is not reintroduced: block.super is the
    parent of *this* template, which is admin/base.html, not Django's
    index."""
    import re
    from pathlib import Path

    import directory

    source = (Path(directory.__file__).parent / "templates" / "admin" / "index.html").read_text()
    # The prose explaining why block.super is wrong mentions it, so
    # compare against the template with its comments stripped.
    active = re.sub(r"\{#.*?#\}", "", source, flags=re.S)
    body = active.split("{% block content %}")[1]
    assert "admin/app_list.html" in body
    assert "block.super" not in body
