"""Structural checks on the published mockup.

It is served straight from GitHub Pages with no build step, so a broken commit
is a broken public page. These checks are fast and need no browser; a real
browser smoke test belongs with the widget once it exists.
"""

import re
from pathlib import Path

import pytest

MOCKUP = Path(__file__).resolve().parents[1] / "mockup" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return MOCKUP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script(html: str) -> str:
    return html.split("<script>")[-1]


def test_is_a_standalone_document(html):
    """It is served directly, not wrapped by an artifact host."""
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "</html>" in html


def test_declares_charset_and_viewport(html):
    """Without a viewport meta the mobile breakpoints silently never apply."""
    assert re.search(r'<meta\s+charset=["\']?utf-8', html, re.I)
    assert re.search(r'<meta\s+name=["\']viewport["\']', html, re.I)


def test_the_charset_is_declared_before_any_text(html):
    """An en dash in the page mojibakes if the encoding is guessed rather than
    declared, and browsers only look at the first 1024 bytes for it.

    This replaces an earlier rule that banned non-ASCII outright. That was a
    workaround for the page being served as a fragment with no charset of its
    own; now that it is a standalone document, declaring the encoding is the
    real fix and prose can use real punctuation.
    """
    head = html[:1024]
    assert re.search(r'<meta\s+charset=["\']?utf-8', head, re.I), (
        "charset must appear in the first 1024 bytes"
    )


def test_no_external_requests_except_google_fonts(html):
    urls = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)', html)
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    external = [u for u in urls if not u.startswith(allowed)]
    # Prose links in the mock chrome are fine; assets are not.
    assets = [u for u in external if re.search(r"\.(js|css|png|jpg|svg|woff2?)(\?|$)", u)]
    assert not assets, f"mockup pulls external assets: {assets}"


# --- it reads the feed rather than carrying a copy ---


def test_no_data_is_embedded(html):
    """A snapshot in the page goes stale the moment anyone edits the registry,
    and silently — the page keeps working and keeps being wrong."""
    assert 'id="seed"' not in html
    assert len(html) < 200_000, "the page should be code, not data"


def test_it_fetches_the_manifest_first(script):
    """The manifest is small and revalidated; the files it names are
    content-hashed and cached forever."""
    assert "manifest.json" in script
    assert "MANIFEST.files.sites.path" in script


def test_coverage_is_fetched_only_when_needed(script):
    """It is roughly fifty times the outlet feed. Most visitors never open a
    view that needs it."""
    assert "loadCoverage" in script
    assert "coverageLoaded" in script


def test_the_browse_view_needs_only_the_outlet_feed(script):
    """Every facet reads the outlet rows, so filtering works before — or
    without — the coverage file arriving."""
    assert "OUTLETS.flatMap(o => multi(o.states))" in script
    assert "OUTLETS.flatMap(o => multi(o.source_files))" in script


def test_a_missing_feed_says_so(script):
    """Rather than rendering an empty directory that looks like real data."""
    assert "showProblem" in script
    assert "No feed published yet" in script


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
