"""Rules encoding the defects found in the LocalNewsDatabase prototype.

Each rule takes the loaded tables and yields Violations. Rules are pure: no I/O,
no globals, so they are equally usable from pytest, a management command, or the
publish job.

ERROR blocks a publish. WARN is reported with counts but does not block —
completeness gaps (a missing county, an unknown medium) are curation backlog,
not corruption, and a permanently red pipeline gets ignored.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

Row = dict[str, str]


class Severity(StrEnum):
    ERROR = "error"
    WARN = "warn"


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: Severity
    message: str
    row_id: str = ""

    def __str__(self) -> str:
        where = f" [{self.row_id}]" if self.row_id else ""
        return f"{self.severity.value.upper():5s} {self.rule}{where}: {self.message}"


# --- controlled vocabularies ------------------------------------------------

MEDIA = frozenset({"Newspaper", "Radio", "Television", "Online", "Magazine", "Public Broadcasting"})

# Values seen in the prototype that are not media at all.
HEADER_TOKENS = frozenset({"type", "state", "outlet name", "url", "medium", "city", "county"})

PLACEHOLDER_DOMAINS = frozenset(
    {"no website", "(no website)", "none", "n/a", "na", "-", "/", "unknown", "tbd"}
)

# Fields permitted in the public export. Anything else is admin-only.
PUBLIC_FIELDS = frozenset(
    {
        "id",
        "outlet_id",
        "name",
        "outlet_name",
        "domain",
        "canonical_url",
        "medium",
        "primary_medium",
        "categories",
        "state",
        "states",
        "city",
        "cities",
        "county",
        "counties",
        "record_count",
        "source_count",
        "source_files",
        # Added with the schema decisions: closures publish, clearly marked;
        # ownership publishes as the owner's name; places publish as a list.
        "status",
        "owner",
        "founded",
        "closed_date",
        "places",
    }
)

# Coverage fields permitted in the public feed. Coverage records are research
# provenance — which study made which claim — so nearly all of it publishes. The
# list is still explicit so a column added upstream is private until reviewed.
COVERAGE_PUBLIC_FIELDS = frozenset(
    {
        "outlet_id",
        "source_file",
        "source_sheet",
        "outlet_name_raw",
        "url",
        "medium",
        "state",
        "county",
        "city",
        "notes",
        "mun_id",
        "gnis",
        "domains_set_length",
        "article_length",
        "ownership",
        "ownership_type",
        "founded",
        "closed_date",
        "updated_on",
        "newsbank_availability",
    }
)

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_URLISH = re.compile(r"^(https?://|www\.)", re.I)


def _blank(v: str | None) -> bool:
    return not (v or "").strip()


# --- outlet rules -----------------------------------------------------------


def rule_outlet_has_name(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    for o in outlets:
        if _blank(o.get("outlet_name")):
            yield Violation(
                "outlet_has_name", Severity.ERROR, "outlet has no name", o.get("outlet_id", "")
            )


def rule_no_header_artifacts(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    """A source spreadsheet parsed at the wrong offset imports its own header."""
    for o in outlets:
        for field in ("outlet_name", "primary_medium", "states"):
            value = (o.get(field) or "").strip().lower()
            if value in HEADER_TOKENS:
                yield Violation(
                    "no_header_artifacts",
                    Severity.ERROR,
                    f"{field}={value!r} is a column header, not data",
                    o.get("outlet_id", ""),
                )


def rule_no_url_in_medium(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    """Column shift in a source file put URLs in the medium column."""
    for o in outlets:
        medium = (o.get("primary_medium") or "").strip()
        if medium and _URLISH.match(medium):
            yield Violation(
                "no_url_in_medium",
                Severity.ERROR,
                f"medium looks like a URL: {medium[:60]!r}",
                o.get("outlet_id", ""),
            )


def rule_domain_normalized(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    """Registrable domain: lowercase, no scheme, no www., no path or port."""
    for o in outlets:
        domain = (o.get("domain") or "").strip()
        if not domain:
            continue
        problems = []
        if _SCHEME.match(domain):
            problems.append("has a scheme")
        if domain.lower().startswith("www."):
            problems.append("has a www. prefix")
        if domain != domain.lower():
            problems.append("is not lowercased")
        if "/" in domain and domain not in PLACEHOLDER_DOMAINS:
            problems.append("contains a path")
        if ":" in domain:
            problems.append("contains a port")
        if problems:
            yield Violation(
                "domain_normalized",
                Severity.ERROR,
                f"{domain!r} " + " and ".join(problems),
                o.get("outlet_id", ""),
            )


def rule_no_placeholder_domain(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    """'no website' as a domain merged 103 unrelated outlets in the prototype."""
    for o in outlets:
        if (o.get("domain") or "").strip().lower() in PLACEHOLDER_DOMAINS:
            yield Violation(
                "no_placeholder_domain",
                Severity.ERROR,
                f"placeholder domain {o.get('domain')!r}; absence must not be an identity",
                o.get("outlet_id", ""),
            )


def rule_medium_in_vocabulary(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    for o in outlets:
        medium = (o.get("primary_medium") or "").strip()
        if not medium:
            yield Violation(
                "medium_in_vocabulary", Severity.WARN, "no medium recorded", o.get("outlet_id", "")
            )
        elif (
            medium not in MEDIA
            and not _URLISH.match(medium)
            and medium.lower() not in HEADER_TOKENS
        ):
            yield Violation(
                "medium_in_vocabulary",
                Severity.WARN,
                f"{medium!r} is outside the controlled vocabulary",
                o.get("outlet_id", ""),
            )


def rule_state_not_abbreviated(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    """The prototype mixes 'MS' and 'Mississippi'. Pick one; full names win."""
    for o in outlets:
        for value in (o.get("states") or "").split(" | "):
            value = value.strip()
            if len(value) == 2 and value.isupper():
                yield Violation(
                    "state_not_abbreviated",
                    Severity.ERROR,
                    f"state {value!r} is an abbreviation, expected the full name",
                    o.get("outlet_id", ""),
                )


def rule_has_domain(outlets: Sequence[Row], **_) -> Iterator[Violation]:
    for o in outlets:
        if _blank(o.get("domain")):
            yield Violation(
                "has_domain", Severity.WARN, "no domain recorded", o.get("outlet_id", "")
            )


# --- merge rules ------------------------------------------------------------


def rule_merge_requires_review(
    outlets: Sequence[Row], coverage: Sequence[Row] = (), **_
) -> Iterator[Violation]:
    """The prototype's central defect: one outlet row covering several outlets.

    An outlet whose coverage rows carry more than one distinct raw name is a
    suspected bad merge and must be flagged for review before it can publish.
    """
    names: dict[str, set[str]] = {}
    for row in coverage:
        oid = row.get("outlet_id", "")
        raw = (row.get("outlet_name_raw") or "").strip().lower()
        if oid and raw:
            names.setdefault(oid, set()).add(raw)

    for o in outlets:
        oid = o.get("outlet_id", "")
        distinct = names.get(oid, set())
        if len(distinct) > 1 and not _truthy(o.get("needs_review")):
            yield Violation(
                "merge_requires_review",
                Severity.ERROR,
                f"merges {len(distinct)} distinct outlet names but is not flagged needs_review",
                oid,
            )


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "y", "t"}


# --- coverage rules ---------------------------------------------------------


def rule_coverage_has_provenance(coverage: Sequence[Row] = (), **_) -> Iterator[Violation]:
    """Provenance is what makes a merge decision reviewable. It is mandatory."""
    for row in coverage:
        if _blank(row.get("source_file")):
            yield Violation(
                "coverage_has_provenance",
                Severity.ERROR,
                "coverage record has no source_file",
                row.get("outlet_id", ""),
            )


def rule_coverage_outlet_resolves(
    outlets: Sequence[Row], coverage: Sequence[Row] = (), **_
) -> Iterator[Violation]:
    known = {o.get("outlet_id", "") for o in outlets}
    for row in coverage:
        oid = (row.get("outlet_id") or "").strip()
        if oid and oid not in known:
            yield Violation(
                "coverage_outlet_resolves",
                Severity.ERROR,
                f"coverage record points at unknown outlet {oid!r}",
                oid,
            )


# --- export rule ------------------------------------------------------------


def rule_export_columns_allowlisted(
    outlets: Sequence[Row], export: Iterable[Row] | None = None, **_
) -> Iterator[Violation]:
    """The guard against publishing an admin field by accident.

    A new column added upstream must be added to PUBLIC_FIELDS deliberately, or
    the publish fails. This is the rule that stops a `paused_reason` ending up on
    the public site.
    """
    for row in export or ():
        extra = sorted(set(row) - PUBLIC_FIELDS)
        if extra:
            yield Violation(
                "export_columns_allowlisted",
                Severity.ERROR,
                f"export carries non-public column(s): {', '.join(extra)}",
                row.get("outlet_id", ""),
            )
        break  # columns are uniform; one row is enough


def rule_coverage_export_allowlisted(
    coverage_export: Iterable[Row] | None = None, **_
) -> Iterator[Violation]:
    """Same guard as the outlet export, for the coverage feed."""
    for row in coverage_export or ():
        extra = sorted(set(row) - COVERAGE_PUBLIC_FIELDS)
        if extra:
            yield Violation(
                "coverage_export_allowlisted",
                Severity.ERROR,
                f"coverage feed carries non-public column(s): {', '.join(extra)}",
                row.get("outlet_id", ""),
            )
        break


RuleFn = Callable[..., Iterator[Violation]]

ALL_RULES: tuple[RuleFn, ...] = (
    rule_outlet_has_name,
    rule_no_header_artifacts,
    rule_no_url_in_medium,
    rule_domain_normalized,
    rule_no_placeholder_domain,
    rule_medium_in_vocabulary,
    rule_state_not_abbreviated,
    rule_has_domain,
    rule_merge_requires_review,
    rule_coverage_has_provenance,
    rule_coverage_outlet_resolves,
    rule_export_columns_allowlisted,
    rule_coverage_export_allowlisted,
)


def run_all(
    outlets: Sequence[Row],
    coverage: Sequence[Row] = (),
    export: Iterable[Row] | None = None,
    coverage_export: Iterable[Row] | None = None,
    rules: Sequence[RuleFn] = ALL_RULES,
) -> list[Violation]:
    found: list[Violation] = []
    for rule in rules:
        found.extend(
            rule(
                outlets=outlets,
                coverage=coverage,
                export=export,
                coverage_export=coverage_export,
            )
        )
    return found
