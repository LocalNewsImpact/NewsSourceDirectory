"""The identity rule, tested against the cases that broke the prototype."""

import pytest

from schema.identity import identity_key, registrable_domain, slugify


class TestRegistrableDomain:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.columbiamissourian.com/", "columbiamissourian.com"),
            ("http://EXAMPLE.com/news", "example.com"),
            ("https://example.com:8080/x", "example.com"),
            ("example.com", "example.com"),
            ("", ""),
        ],
    )
    def test_normalises(self, url, expected):
        assert registrable_domain(url) == expected


class TestSharedHosts:
    """The prototype's central failure: one domain, many outlets."""

    def test_patch_sites_stay_separate(self):
        a = identity_key("https://patch.com/new-jersey/asburypark", "Patch-Asbury Park")
        b = identity_key("https://patch.com/new-jersey/barnegat", "Patch-Barnegat")
        assert a != b

    def test_business_journals_stay_separate(self):
        a = identity_key("https://bizjournals.com/atlanta", "Atlanta Business Chronicle")
        b = identity_key("https://bizjournals.com/nashville", "Nashville Business Journal")
        assert a != b

    def test_facebook_only_outlets_stay_separate(self):
        a = identity_key("https://facebook.com/BernieBanner", "Bernie Banner")
        b = identity_key("https://facebook.com/BlackNews", "Black News")
        assert a != b

    def test_a_shared_host_with_no_path_falls_back_to_the_name(self):
        """facebook.com alone identifies nothing, so it must not become a key."""
        key = identity_key("https://facebook.com", "Some Outlet", "Missouri")
        assert key.startswith("name:")


class TestMissingUrls:
    """'no website' as a domain merged 103 unrelated outlets."""

    @pytest.mark.parametrize("url", ["no website", "(no website)", "N/A", "none", "-", ""])
    def test_placeholders_never_become_an_identity(self, url):
        key = identity_key(url, "The Gleaner", "Kentucky")
        assert key == "name:the-gleaner|kentucky"

    def test_same_name_in_different_states_stays_separate(self):
        a = identity_key("", "The Gleaner", "Kentucky")
        b = identity_key("", "The Gleaner", "Missouri")
        assert a != b

    def test_no_name_and_no_url_yields_nothing_to_merge_on(self):
        assert identity_key("", "") == ""


class TestOrdinaryOutlets:
    def test_generic_paths_are_ignored(self):
        """A /news/ link and a homepage are the same outlet."""
        bare = identity_key("https://www.gordongazettega.com/", "Gordon Gazette")
        news = identity_key("https://www.gordongazettega.com/news", "Gordon Gazette")
        assert bare == news == "gordongazettega.com"

    def test_a_meaningful_path_distinguishes(self):
        a = identity_key("https://example.com/tribune", "Tribune")
        b = identity_key("https://example.com/herald", "Herald")
        assert a != b

    def test_catalogue_urls_are_not_outlet_sites(self):
        """Library of Congress URLs appear in the data as if they were homepages."""
        key = identity_key("https://loc.gov/item/sn12345/", "Allendale County Citizen", "SC")
        assert key.startswith("name:")


class TestAgainstTheRealFixture:
    def test_fixture_produces_more_outlets_than_the_prototype_recorded(self, coverage):
        keys = {identity_key(r["url"], r["outlet_name_raw"], r["state"]) for r in coverage}
        keys.discard("")
        distinct_names = {r["outlet_name_raw"].strip().lower() for r in coverage}
        # The prototype under-counted; the rule should land nearer the name count
        # than the domain count without simply becoming the name count.
        domains = {registrable_domain(r["url"]) for r in coverage if r["url"]}
        assert len(domains) < len(keys) <= len(distinct_names) * 1.2

    def test_no_identity_absorbs_an_implausible_number_of_names(self, coverage):
        from collections import defaultdict

        names = defaultdict(set)
        for r in coverage:
            k = identity_key(r["url"], r["outlet_name_raw"], r["state"])
            if k:
                names[k].add(r["outlet_name_raw"].strip().lower())
        worst = max(names.values(), key=len)
        assert len(worst) <= 12, f"one identity absorbed {len(worst)} names"


def test_slugify():
    assert slugify("Minnetonka / Excelsior Sun") == "minnetonka-excelsior-sun"
