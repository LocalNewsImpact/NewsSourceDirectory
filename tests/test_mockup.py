"""Structural checks on the published mockup.

It is served straight from GitHub Pages with no build step, so a broken commit
is a broken public page. These checks are fast and need no browser; a real
browser smoke test belongs with the widget once it exists.
"""

import json
import re
from pathlib import Path

import pytest

MOCKUP = Path(__file__).resolve().parents[1] / "mockup" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return MOCKUP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def seed(html: str) -> dict:
    m = re.search(r'<script id="seed" type="application/json">(.*?)</script>', html, re.S)
    assert m, "seed payload not found"
    return json.loads(m.group(1))


def test_is_a_standalone_document(html):
    """It is served directly, not wrapped by an artifact host."""
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "</html>" in html


def test_declares_charset_and_viewport(html):
    """Without a viewport meta the mobile breakpoints silently never apply."""
    assert re.search(r'<meta\s+charset=["\']?utf-8', html, re.I)
    assert re.search(r'<meta\s+name=["\']viewport["\']', html, re.I)


def test_script_body_is_ascii_only(html):
    """No charset is guaranteed downstream; a literal en dash mojibakes."""
    body = html.split('<script id="seed"')[0]
    non_ascii = sorted({c for c in body if ord(c) > 127})
    assert not non_ascii, f"non-ASCII outside the data payload: {non_ascii}"


def test_no_external_requests_except_google_fonts(html):
    urls = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)', html)
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    external = [u for u in urls if not u.startswith(allowed)]
    # Prose links in the mock chrome are fine; assets are not.
    assets = [u for u in external if re.search(r"\.(js|css|png|jpg|svg|woff2?)(\?|$)", u)]
    assert not assets, f"mockup pulls external assets: {assets}"


# --- the payload -------------------------------------------------------------


def test_payload_shape(seed):
    assert set(seed) == {"ocols", "ccols", "outlets", "coverage"}
    assert seed["outlets"] and seed["coverage"]


def test_every_row_matches_its_column_list(seed):
    for key, cols in (("outlets", "ocols"), ("coverage", "ccols")):
        width = len(seed[cols])
        bad = [i for i, row in enumerate(seed[key]) if len(row) != width]
        assert not bad, f"{key} rows with wrong width: {bad[:5]}"


def test_payload_carries_no_admin_only_columns(seed):
    """The mockup stands in for the public export; it must not leak admin fields."""
    forbidden = {"paused_reason", "status", "needs_review", "review_note"}
    assert not forbidden & set(seed["ocols"])


def test_coverage_rows_reference_known_outlets(seed):
    oid = seed["ocols"].index("outlet_id")
    cid = seed["ccols"].index("outlet_id")
    known = {row[oid] for row in seed["outlets"]}
    orphans = {row[cid] for row in seed["coverage"]} - known
    assert not orphans, f"coverage rows with no outlet: {sorted(orphans)[:5]}"


# --- every prototype feature is still wired up -------------------------------

REQUIRED_IDS = [
    "m-outlets",
    "m-coverage",
    "m-states",
    "m-sources",  # metric tiles
    "q",  # keyword search
    "ms-state",
    "ms-medium",
    "ms-source",  # the three filters
    "tab-browse",
    "tab-coverage",
    "tab-explorer",  # all three tabs
    "browse-out",
    "cov-head",
    "cov-body",
    "exp-head",
    "exp-body",
    "export",
    "reset",
    "count",
    "chips",
    "range",
]


@pytest.mark.parametrize("element_id", REQUIRED_IDS)
def test_feature_element_present(html, element_id):
    """Parity with the Streamlit prototype — see MIGRATION.md."""
    assert f'id="{element_id}"' in html, f"missing #{element_id}"


def test_filters_are_multi_select(html):
    """The Streamlit original used st.multiselect; single-select loses a capability."""
    assert html.count('type="checkbox"') or "querySelectorAll('.ms input[type=checkbox]')" in html
    assert "new Set()" in html, "facet state should be sets, not scalars"
