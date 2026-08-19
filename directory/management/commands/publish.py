"""Write the public feed from the registry.

    python manage.py publish --out dist/feed
    python manage.py publish --out dist/feed --allow-errors

Reads the database, projects outlets and coverage through the public allowlists,
and hands them to the same builder CI uses — so the rules that guard the feed are
the rules that ran in the pull request, not a second implementation that can
drift from them.

Nothing is published that a rule rejects. `--allow-errors` exists because the
imported prototype data still carries 302 known faults; it makes publishing them
a deliberate act rather than the default.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from directory.models import CoverageRecord, Outlet
from feed.build import build_feed


class Command(BaseCommand):
    help = "Build the public feed from the database."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="dist/feed", type=Path)
        parser.add_argument(
            "--allow-errors", action="store_true", help="publish despite rule errors"
        )
        parser.add_argument("--no-coverage", action="store_true", help="publish outlets only")
        parser.add_argument(
            "--generated-at", default="", help="fixed timestamp, for reproducibility"
        )

    def handle(self, *args, **options):
        outlets = self._outlets()
        if not outlets:
            raise CommandError("no published outlets — nothing to publish")

        coverage = [] if options["no_coverage"] else self._coverage()

        try:
            manifest = build_feed(
                outlets,
                coverage,
                out_dir=options["out"],
                generated_at=options["generated_at"] or None,
                allow_errors=options["allow_errors"],
                include_coverage=not options["no_coverage"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        for meta in manifest["files"].values():
            self.stdout.write(
                f"  {meta['load']:6s} {meta['path']}  "
                f"{meta['rows']} rows, {meta['bytes'] / 1024:.1f}KB"
            )
        self.stdout.write(f"  manifest {options['out']}/manifest.json")
        if manifest["errors_present"]:
            self.stdout.write(
                self.style.WARNING(f"  published with {manifest['errors_present']} rule error(s)")
            )
        self.stdout.write(self.style.SUCCESS("feed written"))

    # -- projection ----------------------------------------------------------

    def _outlets(self) -> list[dict]:
        """Only published outlets, flattened to the shape the rules expect.

        Related objects become their display names rather than ids: the feed is
        read by a browser and by the crawler, and neither can resolve a UUID
        into a medium.
        """
        source_files = self._source_files()
        rows = []
        for outlet in (
            Outlet.objects.filter(is_published=True)
            .select_related("medium", "state", "owner")
            .prefetch_related("places")
            .order_by("name")
        ):
            rows.append(
                {
                    "outlet_id": str(outlet.id),
                    "outlet_name": outlet.name,
                    "canonical_url": outlet.canonical_url,
                    "domain": outlet.domain,
                    "primary_medium": outlet.medium.label if outlet.medium_id else "",
                    "states": outlet.state.name if outlet.state_id else "",
                    "cities": outlet.city,
                    "counties": outlet.county,
                    "owner": outlet.owner.name if outlet.owner_id else "",
                    "status": outlet.status,
                    "founded": outlet.founded_raw,
                    "closed_date": outlet.closed_date_raw,
                    "record_count": str(outlet.record_count),
                    "source_count": str(outlet.source_count),
                    "places": " | ".join(sorted(p.name for p in outlet.places.all())),
                    # Carried on the outlet so the directory view needs nothing
                    # else; coverage stays lazy and most visitors never fetch it.
                    "source_files": " | ".join(sorted(source_files.get(outlet.id, ()))),
                }
            )
        return rows

    def _source_files(self) -> dict:
        """Which studies name each outlet, rolled up so the browse view can
        filter on provenance without loading every coverage record."""
        from collections import defaultdict

        out = defaultdict(set)
        for outlet_id, source_file in CoverageRecord.objects.filter(
            outlet__isnull=False
        ).values_list("outlet_id", "source_file"):
            if source_file:
                out[outlet_id].add(source_file)
        return out

    def _coverage(self) -> list[dict]:
        """Coverage rows for outlets that publish.

        A row belonging to a withheld outlet must not appear: it would leak by
        the back door what the allowlist withheld at the front.
        """
        return [
            {
                "outlet_id": str(record.outlet_id),
                "source_file": record.source_file,
                "source_sheet": record.source_sheet,
                "outlet_name_raw": record.outlet_name_raw,
                "url": record.url,
                "medium": record.medium_raw,
                "state": record.state_raw,
                "county": record.county,
                "city": record.city,
                "notes": record.notes,
                "mun_id": record.mun_id,
                "gnis": record.gnis,
                "ownership": record.ownership,
                "ownership_type": record.ownership_type,
                "founded": record.founded,
                "closed_date": record.closed_date,
                "updated_on": record.updated_on,
                "newsbank_availability": record.newsbank_availability,
            }
            for record in CoverageRecord.objects.filter(
                outlet__isnull=False, outlet__is_published=True
            )
            .select_related("outlet")
            .order_by("source_file", "outlet_name_raw")
        ]
