"""Load a source spreadsheet into CoverageRecord.

    python manage.py import_source coverage_clean.csv
    python manage.py import_source https://raw.githubusercontent.com/.../coverage_clean.csv

Coverage records are ground truth: imported verbatim, never edited by
derivation, and every outlet field must be reproducible from them. Nothing here
normalises, corrects, or drops a value — the raw text is the evidence a merge
decision is later reviewed against.

Deliberately does **not** import the prototype's `outlets_clean.csv` as outlets.
Its dedupe keyed on the bare domain and merged 1,102 distinct outlets into 222
rows; outlets are rebuilt from coverage instead. See MIGRATION.md.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from directory.models import CoverageRecord, SourceImport

# Source column -> model field. Two are renamed to keep "this is untouched
# source text" visible at the point of use.
COLUMNS = {
    "outlet_name_raw": "outlet_name_raw",
    "url": "url",
    "medium": "medium_raw",
    "state": "state_raw",
    "county": "county",
    "city": "city",
    "notes": "notes",
    "mun_id": "mun_id",
    "gnis": "gnis",
    "ownership": "ownership",
    "ownership_type": "ownership_type",
    "founded": "founded",
    "closed_date": "closed_date",
    "updated_on": "updated_on",
    "newsbank_availability": "newsbank_availability",
    "source_file": "source_file",
    "source_sheet": "source_sheet",
    "outlet_id": "legacy_outlet_id",
}
NUMERIC = {"domains_set_length": "domains_set_length", "article_length": "article_length"}

# Strings the sources use to mean "nothing", which must not be stored as data.
NULLISH = {"", "nan", "none", "null", "n/a", "na", "-"}

MAX_LENGTHS = {
    f.name: f.max_length
    for f in CoverageRecord._meta.get_fields()
    if getattr(f, "max_length", None)
}


def clean(value) -> str:
    text = ("" if value is None else str(value)).strip()
    return "" if text.lower() in NULLISH else text


def to_float(value) -> float | None:
    text = clean(value)
    try:
        return float(text)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Import a coverage spreadsheet (csv or xlsx) from a path or URL."

    def add_arguments(self, parser):
        parser.add_argument("source", help="path or https URL to a .csv or .xlsx")
        parser.add_argument("--sheet", default="", help="worksheet name, for xlsx")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="delete earlier imports of the same filename first",
        )
        parser.add_argument("--dry-run", action="store_true", help="report and change nothing")
        parser.add_argument("--limit", type=int, default=0, help="stop after N rows")

    def handle(self, *args, **options):
        source = options["source"]
        name = Path(urlparse(source).path).name or source

        rows = self._read(source, options["sheet"])
        if options["limit"]:
            rows = rows[: options["limit"]]
        if not rows:
            raise CommandError(f"{name} has no rows")

        missing = {"outlet_name_raw"} - set(rows[0])
        if missing:
            raise CommandError(
                f"{name} is missing required column(s): {', '.join(sorted(missing))}"
            )

        skipped = sum(1 for r in rows if not clean(r.get("outlet_name_raw")))
        self.stdout.write(f"{name}: {len(rows)} rows, {skipped} without a name")

        if options["dry_run"]:
            self._preview(rows)
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        with transaction.atomic():
            if options["replace"]:
                removed = CoverageRecord.objects.filter(source_file=name).delete()[0]
                SourceImport.objects.filter(filename=name).delete()
                if removed:
                    self.stdout.write(f"  replaced: removed {removed} earlier record(s)")

            batch = SourceImport.objects.create(filename=name, sheet=options["sheet"], row_count=0)
            created = self._load(rows, batch, name)
            batch.row_count = created
            batch.save(update_fields=["row_count"])

        self.stdout.write(self.style.SUCCESS(f"imported {created} coverage record(s)"))
        self.stdout.write("next: manage.py rebuild_outlets")

    # -- reading -------------------------------------------------------------

    def _read(self, source: str, sheet: str) -> list[dict]:
        if source.startswith(("http://", "https://")):
            with urlopen(source) as response:  # noqa: S310 — operator-supplied URL
                raw = response.read()
        else:
            path = Path(source)
            if not path.exists():
                raise CommandError(f"no such file: {path}")
            raw = path.read_bytes()

        if source.lower().endswith((".xlsx", ".xls")):
            import pandas as pd

            frame = pd.read_excel(io.BytesIO(raw), sheet_name=sheet or 0, dtype=str)
            return frame.to_dict("records")

        text = raw.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    # -- writing -------------------------------------------------------------

    def _load(self, rows: list[dict], batch: SourceImport, name: str) -> int:
        records = []
        for row in rows:
            outlet_name = clean(row.get("outlet_name_raw"))
            if not outlet_name:
                # A row with no outlet names nothing and cannot be reviewed.
                continue

            values = {}
            for column, field in COLUMNS.items():
                text = clean(row.get(column))
                limit = MAX_LENGTHS.get(field)
                # Truncate rather than fail: a long note must not lose the whole
                # row, and the source is preserved in the file itself.
                values[field] = text[:limit] if limit and len(text) > limit else text
            for column, field in NUMERIC.items():
                values[field] = to_float(row.get(column))

            values["source_file"] = values.get("source_file") or name
            records.append(CoverageRecord(source_import=batch, **values))

        CoverageRecord.objects.bulk_create(records, batch_size=1000)
        return len(records)

    def _preview(self, rows: list[dict]) -> None:
        recognised = sorted(set(rows[0]) & (set(COLUMNS) | set(NUMERIC)))
        ignored = sorted(set(rows[0]) - set(recognised))
        self.stdout.write(f"  columns used   : {', '.join(recognised)}")
        if ignored:
            self.stdout.write(f"  columns ignored: {', '.join(ignored)}")
        for row in rows[:3]:
            self.stdout.write(
                f"    {clean(row.get('outlet_name_raw'))[:38]:40s} "
                f"{clean(row.get('state'))[:14]:16s} {clean(row.get('url'))[:40]}"
            )
