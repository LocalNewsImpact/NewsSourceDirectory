"""Seed Place from the USGS Domestic Names National File, then link coverage.

    python manage.py seed_places --file DomesticNames_National_Text.zip --link
    python manage.py seed_places --url  https://prd-tnm.s3.amazonaws.com/...zip

Seeded from the gazetteer rather than from the coverage data, because the
question worth asking is which places are served by *nobody*. A place with no
outlet has no coverage record, so it can only exist here if something else put
it there.

The file is ~37MB zipped and is read straight out of the archive. It is not
committed.
https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data

Two things about the real file that are not obvious:

  * The header is lowercase and carries a BOM, and there is no state
    abbreviation column — state arrives as `state_name` plus `state_numeric`,
    the FIPS code.
  * `Civil` means different things by state. New Jersey municipalities are
    Civil features, so the class cannot be dropped: 506 of the 511 GNIS ids in
    the coverage data are Civil. In Missouri the same class is largely land
    surveys and planning regions, which is why `feature_class` is kept on the
    row rather than collapsed into `kind`.
"""

from __future__ import annotations

import csv
import io
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from directory.models import CoverageRecord, OutletPlace, Place, State

GNIS_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/"
    "DomesticNames/DomesticNames_National_Text.zip"
)

# Somewhere people live, or a civil division. The file is mostly streams,
# summits and cemeteries — 982k rows, of which 256k are these two.
FEATURE_CLASSES = {"Populated Place", "Civil"}

CLASS_TO_KIND = {"Populated Place": Place.Kind.CITY, "Civil": Place.Kind.MUNICIPALITY}


def normalise_gnis(raw: str) -> str:
    """GNIS ids arrive from the source spreadsheets as float strings such as
    '1723212.0'. Without coercion they never match the gazetteer."""
    value = (raw or "").strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value if value.isdigit() else ""


class Command(BaseCommand):
    help = "Seed places from the GNIS national file and link coverage to them."

    def add_arguments(self, parser):
        parser.add_argument("--file", default="", help="the national file, .zip or .txt")
        parser.add_argument("--url", nargs="?", const=GNIS_URL, help="download it instead")
        parser.add_argument("--states", default="", help="limit to these names, e.g. Missouri,Iowa")
        parser.add_argument("--link", action="store_true", help="link coverage after seeding")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not options["file"] and not options["url"]:
            raise CommandError("pass --file or --url")

        wanted = {s.strip().lower() for s in options["states"].split(",") if s.strip()}
        states = {s.name.lower(): s for s in State.objects.all()}
        if not states:
            raise CommandError("no states — run seed_vocabularies first")

        rows = self._rows(options["file"], options["url"], wanted)

        if options["dry_run"]:
            for i, row in enumerate(rows):
                if i >= 5:
                    break
                self.stdout.write(
                    f"    {row['name'][:30]:32s} {row['state_name'][:14]:16s} "
                    f"{row['feature_class']:16s} gnis={row['gnis']}"
                )
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        created = self._seed(rows, states)
        self.stdout.write(self.style.SUCCESS(f"{created} place(s) created"))

        if options["link"]:
            report = self._link()
            for label, n in report.items():
                self.stdout.write(f"  {label:28s} {n}")

    # -- reading -------------------------------------------------------------

    def _rows(self, path: str, url: str | None, wanted: set[str]) -> Iterator[dict]:
        """Yield rows one at a time, never holding the file in memory.

        The first production run was killed by the OOM killer: reading the 37MB
        archive into memory, expanding it to a 147MB string and building a list
        of 256,114 dicts needs far more than a Cloud Run job's default 512Mi.
        Locally it passed, because a laptop does not care.
        """
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "gnis"
            if url:
                self.stdout.write(f"downloading {url}")
                with urlopen(url) as response, local.open("wb") as out:  # noqa: S310
                    shutil.copyfileobj(response, out)
            else:
                source = Path(path)
                if not source.exists():
                    raise CommandError(f"no such file: {source}")
                local = source

            with local.open("rb") as probe:
                is_zip = probe.read(2) == b"PK"

            if is_zip:
                with zipfile.ZipFile(local) as archive:
                    name = next((n for n in archive.namelist() if n.lower().endswith(".txt")), "")
                    if not name:
                        raise CommandError("no .txt inside the archive")
                    with archive.open(name) as raw:
                        yield from self._parse(
                            io.TextIOWrapper(raw, "utf-8", errors="replace"), wanted
                        )
            else:
                with local.open(encoding="utf-8", errors="replace") as handle:
                    yield from self._parse(handle, wanted)

    def _parse(self, handle, wanted: set[str]) -> Iterator[dict]:
        reader = csv.DictReader(handle, delimiter="|")
        # The real header is lowercase and starts with a BOM.
        reader.fieldnames = [f.lstrip("\ufeff").strip().lower() for f in reader.fieldnames or []]
        if "feature_id" not in (reader.fieldnames or []):
            raise CommandError(
                f"unexpected columns: {', '.join((reader.fieldnames or [])[:6])}. "
                "Expected the USGS Domestic Names file."
            )

        for row in reader:
            if row.get("feature_class") not in FEATURE_CLASSES:
                continue
            state_name = (row.get("state_name") or "").strip()
            if wanted and state_name.lower() not in wanted:
                continue
            yield {
                "gnis": (row.get("feature_id") or "").strip(),
                "name": (row.get("feature_name") or "").strip(),
                "state_name": state_name,
                "state_fips": (row.get("state_numeric") or "").strip(),
                "county_fips": (row.get("county_numeric") or "").strip(),
                "county_name": (row.get("county_name") or "").strip(),
                "feature_class": row.get("feature_class", ""),
                "kind": CLASS_TO_KIND.get(row.get("feature_class"), Place.Kind.CITY),
            }

    # -- seeding -------------------------------------------------------------

    BATCH = 5000

    def _seed(self, rows, states: dict) -> int:
        """Insert in batches, holding at most BATCH objects at a time."""
        known = set(Place.objects.exclude(gnis="").values_list("gnis", flat=True))
        batch: list[Place] = []
        created = seen = 0

        def flush():
            nonlocal batch
            if batch:
                Place.objects.bulk_create(batch, batch_size=1000, ignore_conflicts=True)
                batch = []

        for r in rows:
            seen += 1
            if not (r["gnis"] and r["name"]) or r["gnis"] in known:
                continue
            known.add(r["gnis"])
            batch.append(
                Place(
                    name=r["name"],
                    kind=r["kind"],
                    state=states.get(r["state_name"].lower()),
                    gnis=r["gnis"],
                    state_fips=r["state_fips"],
                    county_fips=r["county_fips"],
                    county_name=r["county_name"],
                    feature_class=r["feature_class"],
                    seeded_from_gnis=True,
                )
            )
            created += 1
            if len(batch) >= self.BATCH:
                flush()
        flush()

        self.stdout.write(f"{seen} populated places and civil divisions read")
        return created

    # -- linking -------------------------------------------------------------

    def _link(self) -> dict[str, int]:
        by_gnis = {p.gnis: p for p in Place.objects.exclude(gnis="")}
        by_name: dict[tuple[str, str], Place] = {}
        for place in Place.objects.select_related("state"):
            if place.state_id:
                by_name.setdefault((place.name.lower(), place.state.code), place)

        report = dict.fromkeys(
            ["linked by GNIS id", "matched by name", "GNIS id not a place", "unmatched"], 0
        )
        links: list[OutletPlace] = []

        for record in CoverageRecord.objects.exclude(outlet=None).select_related("outlet"):
            place = method = None

            gnis = normalise_gnis(record.gnis)
            if gnis:
                place = by_gnis.get(gnis)
                if place:
                    method = OutletPlace.MatchMethod.GNIS
                else:
                    # The id exists but names a reservoir, a summit or nothing.
                    # Counted rather than silently dropped: it is a fault in the
                    # source, and the count is how anyone finds out.
                    report["GNIS id not a place"] += 1

            if place is None and record.city and record.state_raw:
                city = record.city.split(",")[0].strip().lower()
                code = self._state_code(record.state_raw)
                if city and code:
                    place = by_name.get((city, code))
                    method = OutletPlace.MatchMethod.NAME if place else None

            if place is None:
                report["unmatched"] += 1
                continue

            links.append(
                OutletPlace(
                    outlet=record.outlet,
                    place=place,
                    source_import_id=record.source_import_id,
                    asserted_by=record.source_file,
                    match_method=method,
                    # A name match is an inference, not a fact.
                    needs_review=method == OutletPlace.MatchMethod.NAME,
                )
            )
            report[
                "linked by GNIS id" if method == OutletPlace.MatchMethod.GNIS else "matched by name"
            ] += 1

        with transaction.atomic():
            OutletPlace.objects.bulk_create(links, batch_size=2000, ignore_conflicts=True)
        return report

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
