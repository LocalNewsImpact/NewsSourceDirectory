"""The merge review, which is the reason this project uses Django at all.

The prototype keyed outlets on the bare domain, so 222 outlets each cover
several real mastheads. Splitting them is the curation work, and the split has
to be safe: it must not lose coverage rows, must not collide on identity keys,
and must leave the original outlet valid.
"""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import AnonymousUser

from directory.admin import OutletAdmin
from directory.models import CoverageRecord, Outlet, SourceImport

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class FakeRequest:
    """Admin actions only touch the messages framework, which needs somewhere
    to write."""

    def __init__(self):
        self.user = AnonymousUser()
        self.session = {}
        self._messages = []
        self.META = {}

    def get_host(self):
        return "testserver"


@pytest.fixture
def admin_instance():
    return OutletAdmin(Outlet, AdminSite())


@pytest.fixture
def source():
    return SourceImport.objects.create(filename="nj.xlsx", row_count=0)


def make_outlet(**kwargs):
    defaults = {"name": "Patch-Asbury Park", "identity_key": "patch.com/new-jersey"}
    return Outlet.objects.create(**{**defaults, **kwargs})


def add_coverage(outlet, source, name, url="", state="New Jersey"):
    return CoverageRecord.objects.create(
        outlet=outlet,
        source_import=source,
        source_file=source.filename,
        outlet_name_raw=name,
        url=url,
        state_raw=state,
    )


def test_split_creates_one_outlet_per_distinct_name(admin_instance, source, monkeypatch):
    outlet = make_outlet()
    add_coverage(outlet, source, "Patch-Asbury Park", "https://patch.com/new-jersey/asburypark")
    add_coverage(outlet, source, "Patch-Asbury Park", "https://patch.com/new-jersey/asburypark")
    add_coverage(outlet, source, "Patch-Barnegat", "https://patch.com/new-jersey/barnegat")
    add_coverage(outlet, source, "Patch-Belleville", "https://patch.com/new-jersey/belleville")

    monkeypatch.setattr(admin_instance, "message_user", lambda *a, **k: None)
    admin_instance.split_by_name(FakeRequest(), Outlet.objects.filter(pk=outlet.pk))

    assert Outlet.objects.count() == 3


def test_split_loses_no_coverage_rows(admin_instance, source, monkeypatch):
    outlet = make_outlet()
    for name in ["A Paper", "A Paper", "B Paper", "C Paper"]:
        add_coverage(outlet, source, name)

    monkeypatch.setattr(admin_instance, "message_user", lambda *a, **k: None)
    admin_instance.split_by_name(FakeRequest(), Outlet.objects.filter(pk=outlet.pk))

    assert CoverageRecord.objects.count() == 4
    assert CoverageRecord.objects.filter(outlet__isnull=True).count() == 0


def test_the_original_keeps_the_best_supported_name(admin_instance, source, monkeypatch):
    """Whichever masthead has the most evidence stays on the original row, so
    the identity key that other things may reference keeps pointing at it."""
    outlet = make_outlet(name="Something Arbitrary")
    for _ in range(3):
        add_coverage(outlet, source, "Majority Gazette")
    add_coverage(outlet, source, "Minority Herald")

    monkeypatch.setattr(admin_instance, "message_user", lambda *a, **k: None)
    admin_instance.split_by_name(FakeRequest(), Outlet.objects.filter(pk=outlet.pk))

    outlet.refresh_from_db()
    assert outlet.name == "Majority Gazette"
    assert outlet.identity_key == "patch.com/new-jersey"


def test_split_leaves_a_consistent_outlet_alone(admin_instance, source, monkeypatch):
    outlet = make_outlet()
    add_coverage(outlet, source, "One Name")
    add_coverage(outlet, source, "One Name")

    monkeypatch.setattr(admin_instance, "message_user", lambda *a, **k: None)
    admin_instance.split_by_name(FakeRequest(), Outlet.objects.filter(pk=outlet.pk))

    assert Outlet.objects.count() == 1


def test_split_products_are_flagged_for_review(admin_instance, source, monkeypatch):
    """A split is a machine's guess at where the seam was. Someone should look."""
    outlet = make_outlet()
    add_coverage(outlet, source, "Kept Name")
    add_coverage(outlet, source, "New Name")

    monkeypatch.setattr(admin_instance, "message_user", lambda *a, **k: None)
    admin_instance.split_by_name(FakeRequest(), Outlet.objects.filter(pk=outlet.pk))

    created = Outlet.objects.exclude(pk=outlet.pk).get()
    assert created.needs_review is True
    assert "Split from" in created.review_note


def test_split_does_not_collide_on_identity_key(admin_instance, source, monkeypatch):
    """Two rows with no URL would otherwise derive the same key and violate the
    unique constraint mid-transaction."""
    outlet = make_outlet()
    add_coverage(outlet, source, "Same Name", url="", state="")
    add_coverage(outlet, source, "Other Name", url="", state="")
    Outlet.objects.create(name="Decoy", identity_key="name:other-name|")

    monkeypatch.setattr(admin_instance, "message_user", lambda *a, **k: None)
    admin_instance.split_by_name(FakeRequest(), Outlet.objects.filter(pk=outlet.pk))

    keys = list(Outlet.objects.values_list("identity_key", flat=True))
    assert len(keys) == len(set(keys)), "identity keys must stay unique"
