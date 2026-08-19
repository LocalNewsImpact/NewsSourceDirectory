"""The admin landing page and the review tools on it.

Django's index lists model names; a reviewer needs to know what is outstanding.
These tests pin the counts that drive that, and the merge action that the split
action has needed since it shipped.
"""

import pytest
from django.contrib.auth import get_user_model

from directory import dashboard
from directory.models import (
    CoverageRecord,
    DataQualityIssue,
    Outlet,
    OutletPlace,
    Place,
    SourceImport,
    State,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def staff_client(client):
    user = get_user_model().objects.create_user(
        username="s@localnewsimpact.org",
        email="s@localnewsimpact.org",
        password="x",
        is_staff=True,
        is_superuser=True,
    )
    client.force_login(user)
    return client


class TestTiles:
    def test_the_review_queue_is_counted(self):
        Outlet.objects.create(name="A", identity_key="a", needs_review=True)
        Outlet.objects.create(name="B", identity_key="b")
        tile = next(t for t in dashboard.review_tiles() if "review" in t.label.lower())
        assert tile.count == 1

    def test_every_tile_links_into_a_filtered_list(self):
        """A count nobody can click is a fact, not a task."""
        for tile in dashboard.review_tiles():
            assert tile.url.startswith("/admin/")

    def test_quality_tiles_group_by_rule(self):
        for rule in ("has_domain", "has_domain", "no_placeholder_domain"):
            DataQualityIssue.objects.create(rule=rule, severity="warn", message="x")
        tiles = {t.label: t.count for t in dashboard.quality_tiles()}
        assert tiles["has domain"] == 2
        assert tiles["no placeholder domain"] == 1

    def test_unserved_counts_civil_divisions_only(self):
        """Counting populated places too turns 31 New Jersey municipalities into
        2,467 hamlets and means nothing."""
        nj = State.objects.create(code="NJ", name="New Jersey")
        Place.objects.create(name="Somewhere", state=nj, feature_class="Civil")
        Place.objects.create(name="Elsewhere", state=nj, feature_class="Civil")
        for i in range(5):
            Place.objects.create(name=f"Hamlet {i}", state=nj, feature_class="Populated Place")
        assert dashboard.unserved_places("NJ").count == 2


class TestIndexPage:
    def test_the_index_renders_the_summary(self, staff_client):
        Outlet.objects.create(name="A", identity_key="a", needs_review=True)
        response = staff_client.get("/admin/")
        assert response.status_code == 200
        assert b"Needs attention" in response.content
        assert b"Data quality" in response.content

    def test_it_says_so_when_no_check_has_run(self, staff_client):
        response = staff_client.get("/admin/")
        assert b"check_data" in response.content


class TestMergeAction:
    @staticmethod
    def run_merge(outlets):
        from django.contrib.admin.sites import AdminSite

        from directory.admin import OutletAdmin

        admin_obj = OutletAdmin(Outlet, AdminSite())
        messages = []
        admin_obj.message_user = lambda r, m, level=None: messages.append(m)
        admin_obj.merge_selected(None, Outlet.objects.filter(pk__in=[o.pk for o in outlets]))
        return messages

    def test_coverage_moves_to_the_survivor(self):
        source = SourceImport.objects.create(filename="a.csv")
        keep = Outlet.objects.create(name="Sun Thisweek", identity_key="k1")
        other = Outlet.objects.create(name="Sun Thisweek (Burnsville)", identity_key="k2")
        for outlet in (keep, other):
            CoverageRecord.objects.create(
                outlet=outlet, source_import=source, source_file="a.csv", outlet_name_raw="x"
            )

        self.run_merge([keep, other])

        assert Outlet.objects.count() == 1
        assert CoverageRecord.objects.filter(outlet=keep).count() == 2

    def test_no_evidence_is_lost(self):
        """Coverage is reassigned before the absorbed outlet is deleted."""
        source = SourceImport.objects.create(filename="a.csv")
        keep = Outlet.objects.create(name="A", identity_key="k1")
        other = Outlet.objects.create(name="B", identity_key="k2")
        CoverageRecord.objects.create(
            outlet=other, source_import=source, source_file="a.csv", outlet_name_raw="x"
        )

        self.run_merge([keep, other])

        assert CoverageRecord.objects.count() == 1
        assert CoverageRecord.objects.get().outlet == keep

    def test_the_survivor_is_no_longer_flagged(self):
        keep = Outlet.objects.create(name="A", identity_key="k1", needs_review=True)
        other = Outlet.objects.create(name="B", identity_key="k2")
        self.run_merge([keep, other])
        keep.refresh_from_db()
        assert keep.needs_review is False
        assert "Merged" in keep.review_note

    def test_one_outlet_is_refused(self):
        only = Outlet.objects.create(name="A", identity_key="k1")
        messages = self.run_merge([only])
        assert any("two or more" in m.lower() for m in messages)
        assert Outlet.objects.count() == 1


class TestPlaceLinkConfirmation:
    def test_confirming_marks_the_link_manual(self):
        """A name match is a guess until a person looks; confirming records that
        someone did."""
        from django.contrib.admin.sites import AdminSite

        from directory.admin import OutletPlaceAdmin

        outlet = Outlet.objects.create(name="A", identity_key="a")
        place = Place.objects.create(name="Somewhere")
        link = OutletPlace.objects.create(
            outlet=outlet,
            place=place,
            needs_review=True,
            match_method=OutletPlace.MatchMethod.NAME,
        )

        admin_obj = OutletPlaceAdmin(OutletPlace, AdminSite())
        admin_obj.message_user = lambda *a, **k: None
        admin_obj.confirm_links(None, OutletPlace.objects.filter(pk=link.pk))

        link.refresh_from_db()
        assert link.needs_review is False
        assert link.match_method == OutletPlace.MatchMethod.MANUAL
