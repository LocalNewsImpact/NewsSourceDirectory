"""Run the data-quality rules and record what they find.

    python manage.py check_data

The same rules that gate publishing, stored so they can be worked from the
admin. Without this the 289 known faults exist only as a number in a workflow
log, which nobody can act on.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from checks.rules import Severity, run_all
from directory.models import CoverageRecord, DataQualityIssue, Outlet


class Command(BaseCommand):
    help = "Check the registry against the data-quality rules."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="report counts, record nothing")

    def handle(self, *args, **options):
        outlets = self._outlets()
        coverage = self._coverage()

        # No export= here. That rule checks the projection publish builds, and
        # passing the registry as its own export reports needs_review as a
        # non-public column, which is true and irrelevant.
        violations = run_all(outlets, coverage)
        errors = [v for v in violations if v.severity is Severity.ERROR]
        warns = [v for v in violations if v.severity is Severity.WARN]

        self.stdout.write(f"{len(outlets)} outlets, {len(coverage)} coverage records")
        self.stdout.write(f"  errors  : {len(errors)}")
        self.stdout.write(f"  warnings: {len(warns)}")

        by_rule: dict[str, int] = {}
        for v in violations:
            by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
        for rule, n in sorted(by_rule.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"    {n:5d}  {rule}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run — nothing recorded"))
            return

        # row_id carries the outlet id for outlet-level rules, so issues can be
        # attached to the record they concern and shown on its page.
        known = set(Outlet.objects.values_list("id", flat=True))
        rows = []
        for v in violations:
            outlet_id = None
            if v.row_id:
                try:
                    import uuid as _uuid

                    candidate = _uuid.UUID(v.row_id)
                    if candidate in known:
                        outlet_id = candidate
                except ValueError:
                    pass
            rows.append(
                DataQualityIssue(
                    rule=v.rule,
                    severity=v.severity.value,
                    message=v.message,
                    row_id=v.row_id,
                    outlet_id=outlet_id,
                )
            )

        with transaction.atomic():
            DataQualityIssue.objects.all().delete()
            DataQualityIssue.objects.bulk_create(rows, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"recorded {len(rows)} issue(s)"))

    # -- projections, matching what publish sends to the same rules ----------

    def _outlets(self) -> list[dict]:
        return [
            {
                "outlet_id": str(o.id),
                "outlet_name": o.name,
                "canonical_url": o.canonical_url,
                "domain": o.domain,
                "primary_medium": o.medium.label if o.medium_id else "",
                "states": o.state.name if o.state_id else "",
                "cities": o.city,
                "counties": o.county,
                "needs_review": "true" if o.needs_review else "",
            }
            for o in Outlet.objects.select_related("medium", "state")
        ]

    def _coverage(self) -> list[dict]:
        return [
            {
                "outlet_id": str(r.outlet_id) if r.outlet_id else "",
                "outlet_name_raw": r.outlet_name_raw,
                "source_file": r.source_file,
            }
            for r in CoverageRecord.objects.all()
        ]
