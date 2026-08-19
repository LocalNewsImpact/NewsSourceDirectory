"""Rebuilding outlets from coverage records.

The prototype merged 1,102 distinct outlets into 222 rows by keying on the bare
domain. These tests pin the properties that make the rebuild safe to run more
than once — above all, that it never undoes curation.
"""

import pytest
from django.core.management import call_command

from directory.models import CoverageRecord, Medium, Outlet, Owner, SourceImport, State

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def source():
    return SourceImport.objects.create(filename="test.csv")


@pytest.fixture
def vocab():
    call_command("seed_vocabularies", verbosity=0)


def coverage(source, name, url="", state="", **extra):
    return CoverageRecord.objects.create(
        source_import=source,
        source_file=source.filename,
        outlet_name_raw=name,
        url=url,
        state_raw=state,
        **extra,
    )


def rebuild(**kwargs):
    call_command("rebuild_outlets", verbosity=0, **kwargs)


class TestIdentity:
    def test_one_outlet_per_identity(self, source):
        coverage(source, "The Gazette", "https://gazette.test/")
        coverage(source, "The Gazette", "https://gazette.test/news")
        rebuild()
        assert Outlet.objects.count() == 1

    def test_a_shared_host_does_not_merge_outlets(self, source):
        """This is the defect the whole rebuild exists to correct."""
        coverage(source, "Patch-Asbury", "https://patch.com/new-jersey/asburypark")
        coverage(source, "Patch-Barnegat", "https://patch.com/new-jersey/barnegat")
        rebuild()
        assert Outlet.objects.count() == 2

    def test_outlets_without_a_url_do_not_all_become_one(self, source):
        """'no website' as a domain merged 103 unrelated outlets in the prototype."""
        coverage(source, "Alpha Herald", "no website", "Missouri")
        coverage(source, "Beta Times", "no website", "Missouri")
        rebuild()
        assert Outlet.objects.count() == 2

    def test_every_coverage_row_is_linked(self, source):
        coverage(source, "A", "https://a.test/")
        coverage(source, "B", "https://b.test/")
        rebuild()
        assert CoverageRecord.objects.filter(outlet__isnull=True).count() == 0


class TestReviewFlagging:
    def test_multiple_names_under_one_identity_are_flagged(self, source):
        coverage(source, "Britt News-Tribune", "https://globegazette.test/")
        coverage(source, "Forest City Summit", "https://globegazette.test/")
        rebuild()
        outlet = Outlet.objects.get()
        assert outlet.needs_review is True
        assert "different outlets" in outlet.review_note

    def test_a_consistent_outlet_is_not_flagged(self, source):
        coverage(source, "The Gazette", "https://gazette.test/")
        coverage(source, "The Gazette", "https://gazette.test/")
        rebuild()
        assert Outlet.objects.get().needs_review is False

    def test_many_records_alone_do_not_flag(self, source):
        """Record count is not the merge signal: a study legitimately lists one
        outlet once per municipality it covers."""
        for _ in range(50):
            coverage(source, "WNYC-FM", "https://wnyc.test/")
        rebuild()
        outlet = Outlet.objects.get()
        assert outlet.record_count == 50
        assert outlet.needs_review is False


class TestDerivedValues:
    def test_the_best_supported_name_wins(self, source):
        for _ in range(3):
            coverage(source, "Majority Gazette", "https://x.test/")
        coverage(source, "Minority Herald", "https://x.test/")
        rebuild()
        assert Outlet.objects.get().name == "Majority Gazette"

    def test_medium_and_state_are_mapped(self, source, vocab):
        coverage(source, "The Paper", "https://p.test/", "MS", medium_raw="Newspaper")
        rebuild()
        outlet = Outlet.objects.get()
        assert outlet.medium == Medium.objects.get(slug="newspaper")
        assert outlet.state == State.objects.get(code="MS")

    def test_unmappable_medium_is_left_empty(self, source, vocab):
        """A header row imported as data must not become a medium."""
        coverage(source, "The Paper", "https://p.test/", medium_raw="Type")
        rebuild()
        assert Outlet.objects.get().medium is None

    def test_owner_variants_collapse_to_one(self, source):
        coverage(source, "A", "https://a.test/", ownership="Townsquare Media, Inc")
        coverage(source, "B", "https://b.test/", ownership="Townsquare Media Inc")
        rebuild()
        assert Owner.objects.count() == 1

    def test_a_closing_date_sets_the_status_and_keeps_the_raw_value(self, source):
        coverage(source, "Gone Gazette", "https://gone.test/", closed_date="2016")
        rebuild()
        outlet = Outlet.objects.get()
        assert outlet.status == Outlet.Status.CLOSED
        assert outlet.closed_date_raw == "2016"
        assert outlet.closed_date.year == 2016

    def test_an_unparseable_date_is_still_kept(self, source):
        coverage(source, "Old Paper", "https://old.test/", founded="sometime in the 1890s")
        rebuild()
        outlet = Outlet.objects.get()
        assert outlet.founded is None
        assert outlet.founded_raw == "sometime in the 1890s"


class TestRerunSafety:
    def test_a_rerun_creates_nothing_new(self, source):
        coverage(source, "The Gazette", "https://gazette.test/")
        rebuild()
        rebuild()
        assert Outlet.objects.count() == 1

    def test_a_rerun_does_not_undo_curation(self, source, vocab):
        """Derivation proposes; people decide. Without this, every rerun would
        silently discard the review work the project exists to enable."""
        coverage(source, "Wrong Name", "https://x.test/", city="Wrongtown")
        rebuild()

        outlet = Outlet.objects.get()
        outlet.name = "Corrected By An Editor"
        outlet.city = "Columbia"
        outlet.save()

        rebuild()

        outlet.refresh_from_db()
        assert outlet.name == "Corrected By An Editor"
        assert outlet.city == "Columbia"

    def test_force_overwrites_deliberately(self, source):
        coverage(source, "Derived Name", "https://x.test/")
        rebuild()
        outlet = Outlet.objects.get()
        outlet.name = "Edited"
        outlet.save()

        rebuild(force=True)

        outlet.refresh_from_db()
        assert outlet.name == "Derived Name"

    def test_counts_refresh_even_without_force(self, source):
        """Counts describe the evidence, not the outlet, so they are always
        rebuilt — otherwise a new import would leave them stale."""
        coverage(source, "The Gazette", "https://gazette.test/")
        rebuild()
        assert Outlet.objects.get().record_count == 1

        coverage(source, "The Gazette", "https://gazette.test/")
        rebuild()
        assert Outlet.objects.get().record_count == 2
