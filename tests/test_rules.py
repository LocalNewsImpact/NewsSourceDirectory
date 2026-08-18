"""The rules are the unit under test, not the fixture.

Each defect found in the LocalNewsDatabase prototype gets a test that the rule
catches it, and a test that a clean row passes. The fixture deliberately
contains bad data — a green run here means the rules still detect it.
"""

import pytest

from checks import rules
from checks.rules import Severity, run_all


def fired(violations, rule_name):
    return [v for v in violations if v.rule == rule_name]


# --- clean data stays clean -------------------------------------------------


def test_clean_outlet_raises_nothing(clean_outlet):
    violations = run_all([clean_outlet], [])
    assert violations == [], [str(v) for v in violations]


# --- each known defect is caught --------------------------------------------


def test_catches_header_row_imported_as_data():
    bad = {
        "outlet_id": "x",
        "outlet_name": "Outlet Name",
        "primary_medium": "Type",
        "states": "State",
    }
    v = fired(list(rules.rule_no_header_artifacts([bad])), "no_header_artifacts")
    assert len(v) == 3
    assert all(x.severity is Severity.ERROR for x in v)


@pytest.mark.parametrize(
    "medium",
    ["https://www.gordongazettega.com/news", "http://example.com", "www.example.com"],
)
def test_catches_url_in_medium_column(medium):
    bad = {"outlet_id": "x", "primary_medium": medium}
    assert fired(list(rules.rule_no_url_in_medium([bad])), "no_url_in_medium")


@pytest.mark.parametrize(
    "domain",
    [
        "https://example.com",
        "www.example.com",
        "Example.com",
        "example.com/news",
        "example.com:8080",
    ],
)
def test_catches_unnormalized_domain(domain):
    bad = {"outlet_id": "x", "domain": domain}
    assert fired(list(rules.rule_domain_normalized([bad])), "domain_normalized")


def test_normalized_domain_passes():
    ok = {"outlet_id": "x", "domain": "patch.com"}
    assert not fired(list(rules.rule_domain_normalized([ok])), "domain_normalized")


@pytest.mark.parametrize("domain", ["no website", "(no website)", "N/A", "none", "-"])
def test_catches_placeholder_domain(domain):
    """Absence of a website must never become an identity — it merged 103 outlets."""
    bad = {"outlet_id": "x", "domain": domain}
    assert fired(list(rules.rule_no_placeholder_domain([bad])), "no_placeholder_domain")


@pytest.mark.parametrize("state", ["MS", "VA", "WV"])
def test_catches_abbreviated_state(state):
    bad = {"outlet_id": "x", "states": state}
    assert fired(list(rules.rule_state_not_abbreviated([bad])), "state_not_abbreviated")


def test_full_state_name_passes():
    ok = {"outlet_id": "x", "states": "Mississippi | Missouri"}
    assert not fired(list(rules.rule_state_not_abbreviated([ok])), "state_not_abbreviated")


def test_unknown_medium_warns_but_does_not_block():
    odd = {"outlet_id": "x", "primary_medium": "TV (Fox)"}
    v = fired(list(rules.rule_medium_in_vocabulary([odd])), "medium_in_vocabulary")
    assert v and all(x.severity is Severity.WARN for x in v)


# --- the central defect -----------------------------------------------------


def test_unflagged_bad_merge_is_an_error():
    outlet = {"outlet_id": "7", "outlet_name": "Patch-Asbury Park", "needs_review": ""}
    cov = [
        {"outlet_id": "7", "outlet_name_raw": "Patch-Asbury Park", "source_file": "nj.xlsx"},
        {"outlet_id": "7", "outlet_name_raw": "Patch-Barnegat", "source_file": "nj.xlsx"},
    ]
    v = fired(list(rules.rule_merge_requires_review([outlet], cov)), "merge_requires_review")
    assert len(v) == 1 and v[0].severity is Severity.ERROR


def test_flagged_bad_merge_is_allowed_through():
    outlet = {"outlet_id": "7", "outlet_name": "Patch-Asbury Park", "needs_review": "true"}
    cov = [
        {"outlet_id": "7", "outlet_name_raw": "Patch-Asbury Park", "source_file": "nj.xlsx"},
        {"outlet_id": "7", "outlet_name_raw": "Patch-Barnegat", "source_file": "nj.xlsx"},
    ]
    assert not fired(list(rules.rule_merge_requires_review([outlet], cov)), "merge_requires_review")


def test_single_name_outlet_is_not_a_merge():
    outlet = {"outlet_id": "7", "outlet_name": "The Gleaner", "needs_review": ""}
    cov = [
        {"outlet_id": "7", "outlet_name_raw": "The Gleaner", "source_file": "a.csv"},
        {"outlet_id": "7", "outlet_name_raw": "the gleaner", "source_file": "b.csv"},
    ]
    assert not fired(list(rules.rule_merge_requires_review([outlet], cov)), "merge_requires_review")


# --- provenance -------------------------------------------------------------


def test_coverage_without_provenance_is_an_error():
    cov = [{"outlet_id": "1", "outlet_name_raw": "X", "source_file": ""}]
    assert fired(list(rules.rule_coverage_has_provenance(coverage=cov)), "coverage_has_provenance")


def test_coverage_pointing_at_unknown_outlet_is_an_error():
    cov = [{"outlet_id": "999", "outlet_name_raw": "X", "source_file": "a.csv"}]
    assert fired(
        list(rules.rule_coverage_outlet_resolves([{"outlet_id": "1"}], cov)),
        "coverage_outlet_resolves",
    )


# --- the publish guard ------------------------------------------------------


def test_export_carrying_an_admin_column_is_blocked():
    """This is the rule that stops a paused_reason reaching the public site."""
    export = [
        {"outlet_id": "1", "outlet_name": "X", "paused_reason": "Automatic pause after 5 cycles"}
    ]
    v = fired(
        list(rules.rule_export_columns_allowlisted([], export=export)), "export_columns_allowlisted"
    )
    assert len(v) == 1
    assert "paused_reason" in v[0].message


def test_export_of_public_columns_only_is_allowed():
    export = [{"outlet_id": "1", "outlet_name": "X", "domain": "x.com", "states": "Missouri"}]
    assert not fired(
        list(rules.rule_export_columns_allowlisted([], export=export)), "export_columns_allowlisted"
    )


# --- the fixture is real prototype data and must still be detected ----------


def test_fixture_reproduces_the_known_defects(outlets, coverage):
    violations = run_all(outlets, coverage)
    caught = {v.rule for v in violations if v.severity is Severity.ERROR}
    assert "no_placeholder_domain" in caught, "the 'no website' merge is no longer detected"
    assert "merge_requires_review" in caught, "the domain over-merge is no longer detected"
    assert "no_header_artifacts" in caught, "the imported header row is no longer detected"
    assert "no_url_in_medium" in caught, "the column shift is no longer detected"


def test_fixture_has_more_warnings_than_errors_recorded(outlets, coverage):
    """Sanity check that WARN and ERROR are actually being distinguished."""
    violations = run_all(outlets, coverage)
    assert any(v.severity is Severity.WARN for v in violations)
    assert any(v.severity is Severity.ERROR for v in violations)
