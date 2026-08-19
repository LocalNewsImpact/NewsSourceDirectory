"""Model behaviour that the rest of the system relies on."""

import pytest
from django.db import IntegrityError, transaction

from directory.models import CoverageRecord, Outlet, Owner, Place, SourceImport, State

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class TestOutlet:
    def test_search_text_is_built_on_save(self):
        """The widget's search reads this, so it must never go stale."""
        state = State.objects.create(code="MO", name="Missouri")
        owner = Owner.objects.create(name="Gannett", match_key="gannett")
        outlet = Outlet.objects.create(
            name="Columbia Missourian",
            domain="columbiamissourian.com",
            identity_key="columbiamissourian.com",
            city="Columbia",
            county="Boone",
            state=state,
            owner=owner,
        )
        expected = [
            "columbia missourian",
            "columbiamissourian.com",
            "boone",
            "missouri",
            "gannett",
        ]
        for term in expected:
            assert term in outlet.search_text

    def test_search_text_follows_a_rename(self):
        outlet = Outlet.objects.create(name="Old Name", identity_key="x.com")
        outlet.name = "New Name"
        outlet.save()
        assert "new name" in outlet.search_text
        assert "old name" not in outlet.search_text

    def test_identity_key_is_unique(self):
        Outlet.objects.create(name="One", identity_key="shared.com")
        with pytest.raises(IntegrityError), transaction.atomic():
            Outlet.objects.create(name="Two", identity_key="shared.com")

    def test_a_shared_domain_is_not_a_conflict(self):
        """patch.com covers hundreds of outlets; the domain must not be unique."""
        Outlet.objects.create(name="Patch A", domain="patch.com", identity_key="patch.com/a")
        Outlet.objects.create(name="Patch B", domain="patch.com", identity_key="patch.com/b")
        assert Outlet.objects.filter(domain="patch.com").count() == 2

    def test_outlets_default_to_operating_and_published(self):
        outlet = Outlet.objects.create(name="X", identity_key="x")
        assert outlet.status == Outlet.Status.OPERATING
        assert outlet.is_published is True

    def test_a_closed_outlet_still_publishes(self):
        """Dropping closures would hide the news deserts this exists to record."""
        outlet = Outlet.objects.create(
            name="Gone Gazette",
            identity_key="gone",
            status=Outlet.Status.CLOSED,
            closed_date_raw="2016",
        )
        assert outlet.is_published is True

    def test_history_records_an_edit(self):
        outlet = Outlet.objects.create(name="Before", identity_key="h")
        outlet.name = "After"
        outlet.save()
        assert outlet.history.count() == 2
        assert outlet.history.earliest().name == "Before"


class TestCoverageRecord:
    def test_deleting_an_outlet_keeps_the_evidence(self):
        """Coverage rows are the source data. Losing them to a curation mistake
        would be unrecoverable."""
        source = SourceImport.objects.create(filename="a.csv")
        outlet = Outlet.objects.create(name="X", identity_key="x")
        CoverageRecord.objects.create(
            outlet=outlet, source_import=source, source_file="a.csv", outlet_name_raw="X"
        )
        outlet.delete()
        assert CoverageRecord.objects.count() == 1
        assert CoverageRecord.objects.get().outlet is None

    def test_deleting_an_import_removes_its_rows(self):
        """A bad import must be reversible as a unit."""
        source = SourceImport.objects.create(filename="bad.csv")
        outlet = Outlet.objects.create(name="X", identity_key="x2")
        CoverageRecord.objects.create(
            outlet=outlet, source_import=source, source_file="bad.csv", outlet_name_raw="X"
        )
        source.delete()
        assert CoverageRecord.objects.count() == 0


class TestPlace:
    def test_gnis_is_unique_when_present(self):
        Place.objects.create(name="Newark", gnis="885195")
        with pytest.raises(IntegrityError), transaction.atomic():
            Place.objects.create(name="Newark Duplicate", gnis="885195")

    def test_many_places_may_have_no_gnis(self):
        """Only New Jersey carries GNIS ids; a blank must not collide."""
        Place.objects.create(name="Springfield", gnis="")
        Place.objects.create(name="Fairview", gnis="")
        assert Place.objects.filter(gnis="").count() == 2

    def test_same_name_in_two_states_is_allowed(self):
        mo = State.objects.create(code="MO", name="Missouri")
        il = State.objects.create(code="IL", name="Illinois")
        Place.objects.create(name="Springfield", state=mo)
        Place.objects.create(name="Springfield", state=il)
        assert Place.objects.filter(name="Springfield").count() == 2
