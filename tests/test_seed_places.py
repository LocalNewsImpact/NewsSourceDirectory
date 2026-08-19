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

# The real header: lowercase, BOM, no state abbreviation column. An earlier
# version of this fixture used invented uppercase names, so it passed while the
# command could never have read the actual file.
HEADER = (
    "\ufeff" "feature_id|feature_name|feature_class|state_name|state_numeric"
    "|county_name|county_numeric"
)
# Real ids and real classifications. New Jersey municipalities are Civil
# features, which is why that class cannot be filtered out.
ROWS = [
    "885195|Demarest|Civil|New Jersey|34|Bergen|003",
    "882089|Pemberton|Civil|New Jersey|34|Burlington|005",
    "885188|Clifton|Civil|New Jersey|34|Passaic|031",
    "765810|Columbia|Populated Place|Missouri|29|Boone|019",
    "999999|Some Creek|Stream|New Jersey|34|Bergen|003",
    "888888|Mount Nowhere|Summit|Missouri|29|Boone|019",
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
        """The national file is 982k rows, of which 256k are places or civil
        divisions; the rest are streams, summits and cemeteries."""
        seed(gnis_file)
        assert Place.objects.count() == 4
        assert not Place.objects.filter(name="Some Creek").exists()

    def test_places_are_attached_to_their_state_by_name(self, gnis_file, vocab):
        """The file names states in full; there is no abbreviation column."""
        seed(gnis_file)
        assert Place.objects.get(name="Demarest").state == State.objects.get(code="NJ")

    def test_fips_codes_are_captured(self, gnis_file, vocab):
        """state_fips + county_fips is the join to Census county data."""
        seed(gnis_file)
        place = Place.objects.get(name="Columbia")
        assert place.state_fips == "29"
        assert place.county_fips == "019"
        assert place.county_name == "Boone"

    def test_the_feature_class_is_kept(self, gnis_file, vocab):
        """'Civil' means municipalities in New Jersey and land surveys in
        Missouri, so the raw value has to survive."""
        seed(gnis_file)
        assert Place.objects.get(name="Demarest").feature_class == "Civil"

    def test_civil_divisions_are_seeded_not_skipped(self, gnis_file, vocab):
        """506 of the 511 GNIS ids in the coverage data are Civil. Filtering the
        class out would break every real link we have."""
        seed(gnis_file)
        assert Place.objects.filter(feature_class="Civil").count() == 3

    def test_seeded_places_are_marked_as_such(self, gnis_file, vocab):
        """So a place someone adds by hand is distinguishable from the gazetteer."""
        seed(gnis_file)
        assert Place.objects.filter(seeded_from_gnis=True).count() == 4

    def test_states_can_be_limited(self, gnis_file, vocab):
        seed(gnis_file, states="Missouri")
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
        assert link.place.name == "Demarest"
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
            gnis="882089",
            state_raw="New Jersey",
        )
        seed(gnis_file, link=True)
        assert OutletPlace.objects.get().asserted_by == "nj.xlsx"
