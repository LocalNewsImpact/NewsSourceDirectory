"""Seed Place from the USGS Domestic Names National File, then link coverage.

    python manage.py seed_places --file DomesticNames_National.txt
    python manage.py seed_places --file ... --states NJ,MO --link

Seeded from the gazetteer rather than from the coverage data, because the
question worth asking is which places are served by *nobody*. A municipality
with no outlet has no coverage record, so a gazetteer built from coverage can
never contain it.

Linking is deliberately two-tier. Only New Jersey carries GNIS ids — 4,480 rows,
all of them — so those links are facts. Everywhere else the place is matched on
name and state, which is an inference, and those links are marked for review
rather than presented as equivalent.

The national file is ~2 million rows and is not committed. Download it from
https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from directory.models import CoverageRecord, OutletPlace, Place, State

# USGS feature classes that correspond to somewhere people live or a civil
# division. The file also carries streams, summits and cemeteries.
FEATURE_CLASSES = {"Populated Place", "Civil"}

CLASS_TO_KIND = {"Populated Place": Place.Kind.CITY, "Civil": Place.Kind.MUNICIPALITY}


def normalise_gnis(raw: str) -> str:
    """GNIS ids arrive from the source spreadsheets as float strings such as
    '1723212.0'. Without coercion they never match the gazetteer."""
    value = (raw or "").strip()
    if not value:
        return ""
    if value.endswith(".0"):
        value = value[:-2]
    return value if value.isdigit() else ""


class Command(BaseCommand):
    help = "Seed places from the GNIS national file and link coverage to them."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="USGS national file (pipe-delimited)")
        parser.add_argument("--states", default="", help="limit to these codes, e.g. NJ,MO")
        parser.add_argument(
            "--link", action="store_true", help="link coverage records after seeding"
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"no such file: {path}")

        wanted = {s.strip().upper() for s in options["states"].split(",") if s.strip()}
        states = {s.code: s for s in State.objects.all()}
        if not states:
            raise CommandError("no states — run seed_vocabularies first")

        rows = self._read(path, wanted)
        self.stdout.write(
            f"{path.name}: {len(rows)} populated places"
            + (f" in {','.join(sorted(wanted))}" if wanted else "")
        )

        if options["dry_run"]:
            for row in rows[:5]:
                self.stdout.write(f"    {row['name'][:34]:36s} {row['state']}  gnis={row['gnis']}")
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        created = self._seed(rows, states)
        self.stdout.write(self.style.SUCCESS(f"{created} place(s) created"))

        if options["link"]:
            exact, inferred, unmatched = self._link()
            self.stdout.write(f"linked by GNIS id : {exact}")
            self.stdout.write(f"matched by name   : {inferred}  (flagged for review)")
            self.stdout.write(f"unmatched         : {unmatched}")

    # -- reading -------------------------------------------------------------

    def _read(self, path: Path, wanted: set[str]) -> list[dict]:
        out = []
        with path.open(encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh, delimiter="|"):
                if row.get("FEATURE_CLASS") not in FEATURE_CLASSES:
                    continue
                code = (row.get("STATE_ALPHA") or "").strip().upper()
                if wanted and code not in wanted:
                    continue
                out.append(
                    {
                        "gnis": (row.get("FEATURE_ID") or "").strip(),
                        "name": (row.get("FEATURE_NAME") or "").strip(),
                        "state": code,
                        "kind": CLASS_TO_KIND.get(row.get("FEATURE_CLASS"), Place.Kind.CITY),
                    }
                )
        return out

    # -- seeding -------------------------------------------------------------

    def _seed(self, rows: list[dict], states: dict) -> int:
        known = set(Place.objects.exclude(gnis="").values_list("gnis", flat=True))
        fresh = [
            Place(
                name=r["name"],
                kind=r["kind"],
                state=states.get(r["state"]),
                gnis=r["gnis"],
                seeded_from_gnis=True,
            )
            for r in rows
            if r["gnis"] and r["gnis"] not in known and r["name"]
        ]
        with transaction.atomic():
            Place.objects.bulk_create(fresh, batch_size=1000, ignore_conflicts=True)
        return len(fresh)

    # -- linking -------------------------------------------------------------

    def _link(self) -> tuple[int, int, int]:
        by_gnis = {p.gnis: p for p in Place.objects.exclude(gnis="")}
        by_name: dict[tuple[str, str], Place] = {}
        for place in Place.objects.select_related("state"):
            if place.state_id:
                by_name.setdefault((place.name.lower(), place.state.code), place)

        exact = inferred = unmatched = 0
        links: list[OutletPlace] = []

        for record in CoverageRecord.objects.exclude(outlet=None).select_related("outlet"):
            place, method = None, None

            gnis = normalise_gnis(record.gnis)
            if gnis and gnis in by_gnis:
                place, method = by_gnis[gnis], OutletPlace.MatchMethod.GNIS

            if place is None and record.city and record.state_raw:
                # "Missoula, MT" and "Missoula" both appear in the city column.
                city = record.city.split(",")[0].strip().lower()
                code = self._state_code(record.state_raw)
                if city and code:
                    place = by_name.get((city, code))
                    method = OutletPlace.MatchMethod.NAME if place else None

            if place is None:
                unmatched += 1
                continue

            links.append(
                OutletPlace(
                    outlet=record.outlet,
                    place=place,
                    source_import_id=record.source_import_id,
                    asserted_by=record.source_file,
                    match_method=method,
                    # A name match is an inference, not a fact. Only GNIS-linked
                    # rows are trusted without a person looking.
                    needs_review=method == OutletPlace.MatchMethod.NAME,
                )
            )
            if method == OutletPlace.MatchMethod.GNIS:
                exact += 1
            else:
                inferred += 1

        with transaction.atomic():
            OutletPlace.objects.bulk_create(links, batch_size=1000, ignore_conflicts=True)
        return exact, inferred, unmatched

    @staticmethod
    def _state_code(raw: str) -> str:
        from directory.vocabulary import state_lookup_key

        found = state_lookup_key(raw)
        if not found:
            return ""
        kind, value = found
        if kind == "code":
            return value
        state = State.objects.filter(name__iexact=value).first()
        return state.code if state else ""
