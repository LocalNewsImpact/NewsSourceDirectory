"""The feed is the only thing the public ever sees, so its guarantees are tested:
the allowlist holds, output is deterministic, and errors block a publish.
"""

import json

import pytest

from checks.rules import PUBLIC_FIELDS
from feed.build import build_feed, public_view

FIXED = "2026-01-01T00:00:00Z"


@pytest.fixture
def clean_rows(clean_outlet):
    return [clean_outlet, {**clean_outlet, "outlet_id": "2", "outlet_name": "KBIA"}]


# --- the allowlist ----------------------------------------------------------


def test_projection_drops_admin_columns():
    rows = public_view([{"outlet_id": "1", "outlet_name": "X", "paused_reason": "auto-paused"}])
    assert "paused_reason" not in rows[0]
    assert set(rows[0]) <= PUBLIC_FIELDS


def test_publish_refuses_when_rules_error(tmp_path):
    bad = [{"outlet_id": "1", "outlet_name": "X", "domain": "no website"}]
    with pytest.raises(ValueError, match="refusing to publish"):
        build_feed(bad, [], out_dir=tmp_path, generated_at=FIXED)


def test_allow_errors_is_explicit(tmp_path):
    """The prototype data still has 302 errors; publishing it must be a choice."""
    bad = [{"outlet_id": "1", "outlet_name": "X", "domain": "no website"}]
    manifest = build_feed(bad, [], out_dir=tmp_path, generated_at=FIXED, allow_errors=True)
    assert manifest["errors_present"] > 0


# --- determinism ------------------------------------------------------------


def test_same_data_produces_same_hash(tmp_path, clean_rows):
    a = build_feed(clean_rows, [], out_dir=tmp_path / "a", generated_at=FIXED)
    b = build_feed(clean_rows, [], out_dir=tmp_path / "b", generated_at="2026-09-09T09:09:09Z")
    assert a["files"]["sites"]["sha256"] == b["files"]["sites"]["sha256"], (
        "hash must depend on data only, not on when it was built"
    )


def test_row_order_does_not_change_the_hash(tmp_path, clean_rows):
    a = build_feed(clean_rows, [], out_dir=tmp_path / "a", generated_at=FIXED)
    b = build_feed(list(reversed(clean_rows)), [], out_dir=tmp_path / "b", generated_at=FIXED)
    assert a["files"]["sites"]["sha256"] == b["files"]["sites"]["sha256"]


def test_changed_data_changes_the_hash(tmp_path, clean_rows):
    a = build_feed(clean_rows, [], out_dir=tmp_path / "a", generated_at=FIXED)
    edited = [{**clean_rows[0], "city": "Jefferson City"}, clean_rows[1]]
    b = build_feed(edited, [], out_dir=tmp_path / "b", generated_at=FIXED)
    assert a["files"]["sites"]["sha256"] != b["files"]["sites"]["sha256"]


# --- what lands on disk -----------------------------------------------------


def test_writes_hashed_file_and_manifest(tmp_path, clean_rows):
    manifest = build_feed(clean_rows, [], out_dir=tmp_path, generated_at=FIXED)
    name = manifest["files"]["sites"]["path"]
    assert name.startswith("sites.") and name.endswith(".json")
    assert name.split(".")[1] == manifest["files"]["sites"]["sha256"][:8]
    assert (tmp_path / name).exists()

    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest
    assert on_disk["counts"]["outlets"] == 2
    assert on_disk["generated_at"] == FIXED


def test_manifest_lists_the_published_fields(tmp_path, clean_rows):
    """The manifest names the columns per file, so a client knows the shape
    before it fetches anything."""
    manifest = build_feed(clean_rows, [], out_dir=tmp_path, generated_at=FIXED)
    fields = manifest["files"]["sites"]["fields"]
    assert "outlet_name" in fields
    assert "paused_reason" not in fields


def test_feed_json_is_a_list_of_flat_objects(tmp_path, clean_rows):
    manifest = build_feed(clean_rows, [], out_dir=tmp_path, generated_at=FIXED)
    data = json.loads((tmp_path / manifest["files"]["sites"]["path"]).read_text())
    assert isinstance(data, list)
    assert all(isinstance(v, str) for row in data for v in row.values())


# --- the lazy coverage feed -------------------------------------------------


def test_coverage_feed_is_written_and_marked_lazy(tmp_path, clean_rows):
    cov = [{"outlet_id": "1", "outlet_name_raw": "X", "source_file": "a.csv", "state": "Missouri"}]
    manifest = build_feed(clean_rows, cov, out_dir=tmp_path, generated_at=FIXED)

    assert manifest["files"]["sites"]["load"] == "eager"
    assert manifest["files"]["coverage"]["load"] == "lazy"
    assert manifest["files"]["coverage"]["join_key"] == "outlet_id"
    assert manifest["files"]["coverage"]["joins_to"] == "sites"
    assert (tmp_path / manifest["files"]["coverage"]["path"]).exists()


def test_coverage_feed_has_its_own_allowlist(tmp_path, clean_rows):
    """A column added to coverage upstream must not publish by default."""
    cov = [
        {
            "outlet_id": "1",
            "outlet_name_raw": "X",
            "source_file": "a.csv",
            "internal_reviewer_note": "looks wrong",
        }
    ]
    manifest = build_feed(clean_rows, cov, out_dir=tmp_path, generated_at=FIXED)
    published = json.loads((tmp_path / manifest["files"]["coverage"]["path"]).read_text())
    assert "internal_reviewer_note" not in published[0]


def test_coverage_can_be_withheld(tmp_path, clean_rows):
    cov = [{"outlet_id": "1", "outlet_name_raw": "X", "source_file": "a.csv"}]
    manifest = build_feed(
        clean_rows, cov, out_dir=tmp_path, generated_at=FIXED, include_coverage=False
    )
    assert "coverage" not in manifest["files"]
    assert manifest["counts"]["coverage_records"] == 0


def test_coverage_rows_join_to_published_outlets(tmp_path, clean_rows):
    cov = [{"outlet_id": "1", "outlet_name_raw": "X", "source_file": "a.csv"}]
    manifest = build_feed(clean_rows, cov, out_dir=tmp_path, generated_at=FIXED)
    sites = json.loads((tmp_path / manifest["files"]["sites"]["path"]).read_text())
    cover = json.loads((tmp_path / manifest["files"]["coverage"]["path"]).read_text())
    known = {r["outlet_id"] for r in sites}
    assert {r["outlet_id"] for r in cover} <= known


def test_coverage_hash_is_independent_of_sites(tmp_path, clean_rows):
    """Changing one file must not churn the other's cache entry."""
    cov = [{"outlet_id": "1", "outlet_name_raw": "X", "source_file": "a.csv"}]
    a = build_feed(clean_rows, cov, out_dir=tmp_path / "a", generated_at=FIXED)
    edited = [{**clean_rows[0], "city": "Jefferson City"}, clean_rows[1]]
    b = build_feed(edited, cov, out_dir=tmp_path / "b", generated_at=FIXED)
    assert a["files"]["sites"]["sha256"] != b["files"]["sites"]["sha256"]
    assert a["files"]["coverage"]["sha256"] == b["files"]["coverage"]["sha256"]
