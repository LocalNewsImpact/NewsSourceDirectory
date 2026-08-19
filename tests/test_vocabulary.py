"""Mapping source free text onto the controlled vocabularies."""

from datetime import date

import pytest

from directory.vocabulary import (
    category_slug,
    medium_slug,
    owner_match_key,
    parse_date,
    state_lookup_key,
)


class TestMedium:
    @pytest.mark.parametrize(
        "raw,slug",
        [
            ("Newspaper", "newspaper"),
            ("Television", "television"),
            ("TV station", "television"),
            ("TV (NBC)", "television"),
            ("TV (Fox)", "television"),
            ("Radio", "radio"),
            ("Online", "online"),
            ("Facebook page", "online"),
            ("Magazine", "magazine"),
            ("Public Broadcasting", "public-broadcasting"),
            ("Public Broadcast", "public-broadcasting"),
            ("  newspaper  ", "newspaper"),
        ],
    )
    def test_known_values_map(self, raw, slug):
        assert medium_slug(raw) == slug

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "Type",  # a column header imported as data
            "https://www.gordongazettega.com/news",  # a column shift
            "www.example.com",
            "WILY 1210 AM / WRXX 95.3 FM",  # call signs, not a medium
        ],
    )
    def test_junk_maps_to_nothing_rather_than_a_guess(self, raw):
        """A missing medium is a curation task; a wrong one is a wrong answer
        nobody notices."""
        assert medium_slug(raw) is None

    @pytest.mark.parametrize("raw", ["Ethnic Outlets", "Network Sites"])
    def test_categories_are_not_media(self, raw):
        assert medium_slug(raw) is None
        assert category_slug(raw) is not None


class TestState:
    def test_a_full_name_is_a_name(self):
        assert state_lookup_key("Missouri") == ("name", "Missouri")

    @pytest.mark.parametrize("raw", ["MS", "va", "WV"])
    def test_a_two_letter_code_is_a_code(self, raw):
        kind, value = state_lookup_key(raw)
        assert kind == "code"
        assert value == raw.upper()

    def test_a_trailing_code_is_extracted(self):
        """Some rows carry 'Missoula, MT' in the state column."""
        assert state_lookup_key("Missoula, MT") == ("code", "MT")

    @pytest.mark.parametrize("raw", ["", "   ", "State"])
    def test_junk_yields_nothing(self, raw):
        assert state_lookup_key(raw) is None


class TestDates:
    def test_a_bare_year_becomes_january(self):
        assert parse_date("2016") == date(2016, 1, 1)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1/18/2019", date(2019, 1, 18)),
            ("10/5/2019", date(2019, 10, 5)),
            ("2019-10-05", date(2019, 10, 5)),
        ],
    )
    def test_real_dates_parse(self, raw, expected):
        assert parse_date(raw) == expected

    @pytest.mark.parametrize("raw", ["", "sometime in the 90s", "n/a", "circa 2001"])
    def test_unparseable_returns_none_and_never_raises(self, raw):
        """The raw value is kept alongside, so nothing is lost by failing here."""
        assert parse_date(raw) is None


class TestOwnerMatching:
    def test_corporate_suffixes_do_not_split_a_chain(self):
        assert owner_match_key("Townsquare Media, Inc") == owner_match_key("Townsquare Media Inc")

    def test_punctuation_and_case_do_not_split_a_chain(self):
        assert owner_match_key("Adams Publishing Group") == owner_match_key(
            "adams publishing  group"
        )

    def test_different_owners_stay_different(self):
        assert owner_match_key("Gannett") != owner_match_key("Lee Enterprises")
