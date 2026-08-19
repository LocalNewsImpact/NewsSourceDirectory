"""Seeding places from GNIS and linking coverage to them.

The point of seeding from the gazetteer rather than from coverage is to be able
to see places served by nobody. A place with no outlet has no coverage record,
so it can only exist if something else put it there.
"""

import pytest
from django.core.management import call_command

from directory.management.commands.seed_places import normalise_gnis
from directory.models import CoverageRecord, Outlet, OutletPlace, Place, SourceImport, State

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

HEADER = "FEATURE_ID|FEATURE_NAME|FEATURE_CLASS|STATE_ALPHA|COUNTY_NAME"
ROWS = [
    "885195|Newark|Populated Place|NJ|Essex",
    "885196|Montclair|Populated Place|NJ|Essex",
    "885197|Bloomfield|Civil|NJ|Essex",
    "765810|Columbia|Populated Place|MO|Boone",
    "999999|Some Creek|Stream|NJ|Essex",  # wrong feature class
    "888888|Mount Nowhere|Summit|MO|Boone",  # wrong feature class
]


@pytest.fixture
def gnis_file(tmp_path):
    path = tmp_path / "DomesticNames_National.txt"
    path.write_text("\n".join([HEADER, *ROWS]) + "\n")
    return str(path)


@pytest.fixture
def vocab():
    call_command("seed_vocabularies", verbosity=0)


def seed(path, **kwargs):
    call_command("seed_places", file=path, verbosity=0, **kwargs)


class TestSeeding:
    def test_only_places_people_live_in_are_seeded(self, gnis_file, vocab):
        """The national file is mostly streams, summits and cemeteries."""
        seed(gnis_file)
        assert Place.objects.count() == 4
        assert not Place.objects.filter(name="Some Creek").exists()

    def test_places_are_attached_to_their_state(self, gnis_file, vocab):
        seed(gnis_file)
        assert Place.objects.get(name="Newark").state == State.objects.get(code="NJ")

    def test_seeded_places_are_marked_as_such(self, gnis_file, vocab):
        """So a place someone adds by hand is distinguishable from the gazetteer."""
        seed(gnis_file)
        assert Place.objects.filter(seeded_from_gnis=True).count() == 4

    def test_states_can_be_limited(self, gnis_file, vocab):
        seed(gnis_file, states="MO")
        assert Place.objects.count() == 1

    def test_reseeding_creates_nothing_new(self, gnis_file, vocab):
        seed(gnis_file)
        seed(gnis_file)
        assert Place.objects.count() == 4

    def test_dry_run_writes_nothing(self, gnis_file, vocab):
        seed(gnis_file, dry_run=True)
        assert Place.objects.count() == 0

    def test_a_seeded_place_with_no_outlet_still_exists(self, gnis_file, vocab):
        """This is the whole reason for seeding: 'served by nobody' is only
        answerable if the place is in the table."""
        seed(gnis_file)
        assert Place.objects.filter(outlets__isnull=True).count() == 4


class TestGnisNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [("1723212.0", "1723212"), ("1723212", "1723212"), ("", ""), ("nan", ""), ("abc", "")],
    )
    def test_float_strings_are_coerced(self, raw, expected):
        """The source stores GNIS ids as '1723212.0'. Uncoerced they never match."""
        assert normalise_gnis(raw) == expected


class TestLinking:
    @pytest.fixture
    def outlet(self):
        return Outlet.objects.create(name="The Star-Ledger", identity_key="nj.com")

    @pytest.fixture
    def source(self):
        return SourceImport.objects.create(filename="nj.xlsx")

    def test_a_gnis_id_links_exactly_and_is_trusted(self, gnis_file, vocab, outlet, source):
        CoverageRecord.objects.create(
            outlet=outlet,
            source_import=source,
            source_file="nj.xlsx",
            outlet_name_raw="The Star-Ledger",
            gnis="885195.0",
            state_raw="New Jersey",
        )
        seed(gnis_file, link=True)
        link = OutletPlace.objects.get()
        assert link.place.name == "Newark"
        assert link.match_method == OutletPlace.MatchMethod.GNIS
        assert link.needs_review is False

    def test_a_name_match_is_linked_but_flagged(self, gnis_file, vocab, outlet, source):
        """Only New Jersey carries GNIS ids; everywhere else is an inference."""
        CoverageRecord.objects.create(
            outlet=outlet,
            source_import=source,
            source_file="mo.csv",
            outlet_name_raw="Columbia Missourian",
            city="Columbia",
            state_raw="MO",
        )
        seed(gnis_file, link=True)
        link = OutletPlace.objects.get()
        assert link.place.name == "Columbia"
        assert link.match_method == OutletPlace.MatchMethod.NAME
        assert link.needs_review is True

    def test_a_city_with_a_trailing_state_still_matches(self, gnis_file, vocab, outlet, source):
        """The city column carries both 'Columbia' and 'Columbia, MO'."""
        CoverageRecord.objects.create(
            outlet=outlet,
            source_import=source,
            source_file="mo.csv",
            outlet_name_raw="X",
            city="Columbia, MO",
            state_raw="MO",
        )
        seed(gnis_file, link=True)
        assert OutletPlace.objects.count() == 1

    def test_an_unknown_place_links_to_nothing(self, gnis_file, vocab, outlet, source):
        CoverageRecord.objects.create(
            outlet=outlet,
            source_import=source,
            source_file="x.csv",
            outlet_name_raw="X",
            city="Atlantis",
            state_raw="NJ",
        )
        seed(gnis_file, link=True)
        assert OutletPlace.objects.count() == 0

    def test_the_evidence_for_each_link_is_recorded(self, gnis_file, vocab, outlet, source):
        CoverageRecord.objects.create(
            outlet=outlet,
            source_import=source,
            source_file="nj.xlsx",
            outlet_name_raw="X",
            gnis="885196",
            state_raw="New Jersey",
        )
        seed(gnis_file, link=True)
        assert OutletPlace.objects.get().asserted_by == "nj.xlsx"
