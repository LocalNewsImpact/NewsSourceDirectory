"""Derive outlets from coverage records.

    python manage.py rebuild_outlets

The prototype keyed outlets on the bare registrable domain, which merged 1,102
distinct outlets into 222 rows. This rebuilds them on the identity rule in
directory/identity.py instead — host plus first meaningful path segment, or
name and state where there is no usable URL.

**Derivation proposes; people decide.** An outlet that already exists keeps every
value an editor has set. Only blank fields are filled and only counts are
refreshed, unless --force is given. Otherwise a rerun would quietly undo the
review work this whole exercise exists to make possible.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from directory.identity import identity_key, registrable_domain
from directory.models import (
    Category,
    CoverageRecord,
    Medium,
    Outlet,
    Owner,
    State,
)
from directory.vocabulary import (
    category_slug,
    medium_slug,
    owner_match_key,
    parse_date,
    state_lookup_key,
)


def most_common(values) -> str:
    """The value with the most evidence behind it, ties broken alphabetically
    so a rerun on unchanged data produces the same answer."""
    counts = Counter(v for v in values if v)
    if not counts:
        return ""
    top = max(counts.values())
    return sorted(v for v, n in counts.items() if n == top)[0]


class Command(BaseCommand):
    help = "Rebuild outlets from coverage records using the identity rule."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
        parser.add_argument(
            "--force",
            action="store_true",
            help="overwrite curated values (destroys review work — be sure)",
        )

    def handle(self, *args, **options):
        records = list(CoverageRecord.objects.all())
        if not records:
            self.stdout.write(self.style.WARNING("no coverage records — run import_source first"))
            return

        groups: dict[str, list[CoverageRecord]] = defaultdict(list)
        unkeyed = 0
        for record in records:
            key = identity_key(record.url, record.outlet_name_raw, record.state_raw)
            if not key:
                unkeyed += 1
                continue
            groups[key].append(record)

        suspect = {k: v for k, v in groups.items() if self._distinct_names(v) > 1}

        self.stdout.write(f"coverage records   : {len(records)}")
        self.stdout.write(f"identities         : {len(groups)}")
        self.stdout.write(f"  merging >1 name  : {len(suspect)}  (flagged for review)")
        if unkeyed:
            self.stdout.write(f"  unkeyable rows   : {unkeyed}")

        legacy = len({r.legacy_outlet_id for r in records if r.legacy_outlet_id})
        if legacy:
            self.stdout.write(f"prototype claimed  : {legacy} outlets")

        if options["dry_run"]:
            self._preview(suspect)
            self.stdout.write(self.style.WARNING("dry run — nothing written"))
            return

        vocab = self._vocabulary()
        created = updated = 0
        with transaction.atomic():
            for key, rows in groups.items():
                _, was_created = self._apply(key, rows, vocab, force=options["force"])
                created += was_created
                updated += not was_created

        self.stdout.write(self.style.SUCCESS(f"{created} outlet(s) created, {updated} updated"))
        flagged = Outlet.objects.filter(needs_review=True).count()
        self.stdout.write(f"{flagged} outlet(s) await review")

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _distinct_names(rows) -> int:
        return len({r.outlet_name_raw.strip().lower() for r in rows if r.outlet_name_raw.strip()})

    def _vocabulary(self) -> dict:
        return {
            "media": {m.slug: m for m in Medium.objects.all()},
            "categories": {c.slug: c for c in Category.objects.all()},
            "states_by_code": {s.code: s for s in State.objects.all()},
            "states_by_name": {s.name.lower(): s for s in State.objects.all()},
        }

    def _state_for(self, rows, vocab) -> State | None:
        for raw in (r.state_raw for r in rows):
            found = state_lookup_key(raw)
            if not found:
                continue
            kind, value = found
            state = (
                vocab["states_by_code"].get(value)
                if kind == "code"
                else vocab["states_by_name"].get(value.lower())
            )
            if state:
                return state
        return None

    def _owner_for(self, rows) -> Owner | None:
        name = most_common(r.ownership for r in rows)
        if not name:
            return None
        key = owner_match_key(name)
        if not key:
            return None
        owner, _ = Owner.objects.get_or_create(
            match_key=key,
            defaults={
                "name": name,
                "ownership_type": most_common(r.ownership_type for r in rows),
            },
        )
        return owner

    def _apply(self, key: str, rows: list[CoverageRecord], vocab: dict, force: bool):
        outlet = Outlet.objects.filter(identity_key=key).first()
        created = outlet is None
        if created:
            outlet = Outlet(identity_key=key)

        with_url = [r for r in rows if r.url]
        founded_raw = most_common(r.founded for r in rows)
        closed_raw = most_common(r.closed_date for r in rows)

        proposed = {
            "name": most_common(r.outlet_name_raw for r in rows),
            "canonical_url": with_url[0].url if with_url else "",
            "domain": registrable_domain(with_url[0].url) if with_url else "",
            "city": most_common(r.city for r in rows),
            "county": most_common(r.county for r in rows),
            "state": self._state_for(rows, vocab),
            "medium": vocab["media"].get(
                medium_slug(most_common(r.medium_raw for r in rows)) or ""
            ),
            "owner": self._owner_for(rows),
            "founded_raw": founded_raw,
            "founded": parse_date(founded_raw),
            "closed_date_raw": closed_raw,
            "closed_date": parse_date(closed_raw),
            "newsbank_availability": most_common(r.newsbank_availability for r in rows),
        }

        for field, value in proposed.items():
            if value in (None, ""):
                continue
            # Blank fields are filled; curated ones are left alone. This is what
            # makes a rerun safe after someone has corrected a record by hand.
            if created or force or not getattr(outlet, field, None):
                setattr(outlet, field, value)

        if proposed["closed_date_raw"] and outlet.status == Outlet.Status.OPERATING:
            outlet.status = Outlet.Status.CLOSED

        # Always refreshed: these describe the evidence, not the outlet.
        outlet.record_count = len(rows)
        outlet.source_count = len({r.source_file for r in rows})
        if self._distinct_names(rows) > 1:
            outlet.needs_review = True
            outlet.review_note = (
                f"Coverage names {self._distinct_names(rows)} different outlets — "
                "confirm or use the split action."
            )

        outlet.save()

        slug = category_slug(most_common(r.medium_raw for r in rows))
        if slug and slug in vocab["categories"]:
            outlet.categories.add(vocab["categories"][slug])

        CoverageRecord.objects.filter(pk__in=[r.pk for r in rows]).update(outlet=outlet)
        return outlet, created

    def _preview(self, suspect: dict) -> None:
        worst = sorted(suspect.items(), key=lambda kv: -self._distinct_names(kv[1]))[:8]
        if not worst:
            return
        self.stdout.write("\nworst merges:")
        for key, rows in worst:
            names = sorted({r.outlet_name_raw.strip() for r in rows})
            self.stdout.write(
                f"  {self._distinct_names(rows):4d} names  {key[:44]:46s} {names[:2]}"
            )
