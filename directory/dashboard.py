"""The admin landing page.

Django's index lists model names alphabetically, which answers "what tables
exist" rather than "what needs doing". This replaces it with the counts that
represent outstanding work, each linking into the changelist already filtered to
those rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import Count, Q

from directory.models import (
    CoverageRecord,
    DataQualityIssue,
    Outlet,
    OutletPlace,
    Place,
    State,
)


@dataclass(frozen=True)
class Tile:
    label: str
    count: int
    url: str
    note: str = ""
    tone: str = ""  # "" | "warn" | "bad"


def _outlets(**params) -> str:
    return f"/admin/directory/outlet/?{urlencode(params)}" if params else "/admin/directory/outlet/"


def review_tiles() -> list[Tile]:
    """What a reviewer should work on, most actionable first."""
    merges = Outlet.objects.filter(needs_review=True).count()
    no_domain = Outlet.objects.filter(domain="", is_published=True).count()
    no_medium = Outlet.objects.filter(medium__isnull=True, is_published=True).count()
    inferred = OutletPlace.objects.filter(needs_review=True).count()

    return [
        Tile(
            "Outlets needing review",
            merges,
            _outlets(needs_review__exact=1),
            "coverage names more than one masthead",
            "bad" if merges else "",
        ),
        Tile(
            "No domain recorded",
            no_domain,
            _outlets(domain__exact=""),
            "cannot be linked to the crawler",
            "warn" if no_domain else "",
        ),
        Tile(
            "No medium recorded",
            no_medium,
            _outlets(medium__isnull="True"),
            "missing from every medium facet",
            "warn" if no_medium else "",
        ),
        Tile(
            "Place links to confirm",
            inferred,
            "/admin/directory/outletplace/?needs_review__exact=1",
            "matched on name, not a GNIS id",
            "warn" if inferred else "",
        ),
    ]


def quality_tiles() -> list[Tile]:
    """Rule violations, by rule, from the last check_data run."""
    rows = (
        DataQualityIssue.objects.values("rule", "severity").annotate(n=Count("id")).order_by("-n")
    )
    return [
        Tile(
            r["rule"].replace("_", " "),
            r["n"],
            f"/admin/directory/dataqualityissue/?rule__exact={r['rule']}",
            "blocks publishing" if r["severity"] == "error" else "warning",
            "bad" if r["severity"] == "error" else "warn",
        )
        for r in rows
    ]


def registry_tiles() -> list[Tile]:
    """The shape of the registry, for orientation rather than action."""
    counts = Outlet.objects.aggregate(
        total=Count("id"),
        published=Count("id", filter=Q(is_published=True)),
        closed=Count("id", filter=Q(status="closed")),
    )
    return [
        Tile("Outlets", counts["total"], _outlets()),
        Tile("Published", counts["published"], _outlets(is_published__exact=1)),
        Tile("Closed", counts["closed"], _outlets(status__exact="closed")),
        Tile(
            "Coverage records", CoverageRecord.objects.count(), "/admin/directory/coveragerecord/"
        ),
        Tile("Places", Place.objects.count(), "/admin/directory/place/"),
    ]


def unserved_places(state_code: str = "NJ") -> Tile:
    """Places with no outlet — the question the gazetteer exists to answer.

    Restricted to civil divisions. Counting populated places as well would
    report every unincorporated hamlet as unserved, which in New Jersey turns 31
    into 2,467 and means nothing.
    """
    state = State.objects.filter(code=state_code).first()
    if state is None:
        return Tile(f"{state_code} municipalities with no outlet", 0, "/admin/directory/place/")

    qs = Place.objects.filter(state=state, feature_class="Civil")
    total = qs.count()
    served = qs.annotate(n=Count("outlets", distinct=True)).filter(n__gt=0).count()

    # state__id__exact, not state__code__exact: the admin only permits lookups
    # registered in list_filter, and rejects anything else with a 400.
    url = (
        "/admin/directory/place/"
        f"?served=none&feature_class__exact=Civil&state__id__exact={state.pk}"
    )
    return Tile(
        f"{state_code} municipalities with no outlet",
        total - served,
        url,
        f"of {total} civil divisions",
        "warn" if total - served else "",
    )
