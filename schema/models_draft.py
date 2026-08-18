"""DRAFT Django models for the News Source Directory.

Not wired into a project yet — this is a schema proposal to react to, drafted
against the real columns in mwe400/LocalNewsDatabase (outlets_clean.csv and
coverage_clean.csv). See MIGRATION.md for why the prototype's outlet table
cannot be imported as-is.

Three ideas run through it:

1. CoverageRecord is ground truth. It is imported verbatim and never edited by
   derivation. Every Outlet field must be reproducible from it.
2. Identity is not the bare domain. Sharing patch.com does not make two outlets
   the same outlet.
3. Public and admin are separated at the table level, not by column flags.
   Outlet publishes; CoverageRecord never leaves the admin.
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords

# Fields written to the public export. Named explicitly so a future column
# cannot be published by accident — see MIGRATION.md.
PUBLIC_FIELDS = (
    "id", "name", "domain", "canonical_url",
    "medium", "categories", "state", "city", "county",
)

# Path segments that do not distinguish one outlet from another.
GENERIC_PATH_SEGMENTS = {"", "news", "home", "index", "index.html"}


class Medium(models.Model):
    """Controlled vocabulary: Newspaper, Radio, Television, Online, Magazine,
    Public Broadcasting. Replaces the 18 free-text values in the prototype."""

    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=64, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ("sort_order", "label")

    def __str__(self):
        return self.label


class Category(models.Model):
    """A second axis the prototype conflated with medium: 'Ethnic Outlets',
    'Network Sites'. An outlet has one medium and any number of categories."""

    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("label",)
        verbose_name_plural = "categories"

    def __str__(self):
        return self.label


class State(models.Model):
    """Controlled vocabulary. The prototype mixed 'MS' and 'Mississippi', and
    admitted a literal 'State' from a stray header row."""

    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class SourceImport(models.Model):
    """One import run of one file. Gives every CoverageRecord a traceable
    origin and makes a bad import reversible as a unit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    sheet = models.CharField(max_length=255, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.CharField(max_length=255, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-imported_at",)

    def __str__(self):
        return f"{self.filename} ({self.row_count} rows)"


class Outlet(models.Model):
    """A news outlet. Derived from CoverageRecord, then curated by hand.

    Every field here is editable in the admin: derivation proposes, people
    decide. `identity_key` is what makes a re-run of rebuild_outlets idempotent
    without re-merging what an editor has already split apart.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255)
    canonical_url = models.URLField(max_length=500, blank=True)

    # Registrable domain: lowercased, no scheme, no 'www.'. Indexed but NOT
    # unique — patch.com legitimately covers hundreds of distinct outlets.
    # This is the join key to the crawler; it is not an identity.
    domain = models.CharField(max_length=255, blank=True, db_index=True)

    # host + first meaningful path segment, or slug(name)|state when there is
    # no URL. See MIGRATION.md for the rule and its caveats.
    identity_key = models.CharField(max_length=500, unique=True)

    medium = models.ForeignKey(
        Medium, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="outlets")

    state = models.ForeignKey(
        State, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )
    city = models.CharField(max_length=128, blank=True)
    county = models.CharField(max_length=128, blank=True)

    # Outlet-level attributes that sit in coverage rows in the prototype and
    # are rolled up here. Sparse in the source data (ownership 832/8561,
    # founded 414/8561, closed_date 92/8561).
    ownership = models.CharField(max_length=255, blank=True)
    ownership_type = models.CharField(max_length=128, blank=True)
    founded = models.CharField(max_length=32, blank=True)
    closed_date = models.CharField(max_length=32, blank=True)
    newsbank_availability = models.CharField(max_length=128, blank=True)

    # Denormalized search blob, regenerated on save. The prototype's
    # search_text, kept because it was the right idea.
    search_text = models.TextField(blank=True, editable=False)

    # Rollups from CoverageRecord. record_count is the tell for a bad merge.
    record_count = models.PositiveIntegerField(default=0, editable=False)
    source_count = models.PositiveIntegerField(default=0, editable=False)

    needs_review = models.BooleanField(default=False, db_index=True)
    review_note = models.TextField(blank=True)

    # Withheld rows stay in the admin and out of sites.json.
    is_published = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ("name",)
        indexes = [
            models.Index(fields=["is_published", "name"]),
            models.Index(fields=["needs_review", "record_count"]),
        ]

    def __str__(self):
        return self.name


class CoverageRecord(models.Model):
    """One row from one source spreadsheet, preserved verbatim.

    Nothing here is normalized or corrected. Raw values are the evidence a
    merge decision is reviewed against, so they must survive intact. The `_raw`
    suffix marks fields deliberately left as free text.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Null while a row is unassigned, e.g. after a merge is split apart.
    outlet = models.ForeignKey(
        Outlet, null=True, blank=True, on_delete=models.SET_NULL, related_name="coverage"
    )
    source_import = models.ForeignKey(
        SourceImport, on_delete=models.CASCADE, related_name="records"
    )

    source_file = models.CharField(max_length=255, db_index=True)
    source_sheet = models.CharField(max_length=255, blank=True)

    outlet_name_raw = models.CharField(max_length=255)
    url = models.URLField(max_length=500, blank=True)
    medium_raw = models.CharField(max_length=255, blank=True)
    state_raw = models.CharField(max_length=128, blank=True)
    county = models.CharField(max_length=128, blank=True)
    city = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)

    # New Jersey municipality identifiers, present on 4,480 rows.
    mun_id = models.CharField(max_length=64, blank=True)
    gnis = models.CharField(max_length=64, blank=True)

    # Montana-only measures, present on 1,117 rows.
    domains_set_length = models.FloatField(null=True, blank=True)
    article_length = models.FloatField(null=True, blank=True)

    ownership = models.CharField(max_length=255, blank=True)
    ownership_type = models.CharField(max_length=128, blank=True)
    founded = models.CharField(max_length=32, blank=True)
    closed_date = models.CharField(max_length=32, blank=True)
    updated_on = models.CharField(max_length=32, blank=True)
    newsbank_availability = models.CharField(max_length=128, blank=True)

    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("source_file", "outlet_name_raw")
        indexes = [
            models.Index(fields=["outlet", "source_file"]),
            models.Index(fields=["outlet_name_raw"]),
        ]

    def __str__(self):
        return f"{self.outlet_name_raw} ({self.source_file})"


class Collection(models.Model):
    """A named subset of the registry. This is the unit handed to the crawler:
    the slug becomes a crawler dataset slug, and each Outlet id lands in
    dataset_sources.legacy_host_id, which is uniquely constrained per dataset
    and so makes re-ingest idempotent.

    A real join table rather than tags, so a collection can carry its own
    metadata and a stable slug.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    outlets = models.ManyToManyField(Outlet, blank=True, related_name="collections")

    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ("label",)

    def __str__(self):
        return self.label
