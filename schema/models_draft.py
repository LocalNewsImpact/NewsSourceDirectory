"""DRAFT Django models for the News Source Directory.

Not wired into a project yet — this is a schema proposal to react to, drafted
against the real columns in mwe400/LocalNewsDatabase (outlets_clean.csv and
coverage_clean.csv). See MIGRATION.md for why the prototype's outlet table
cannot be imported as-is.

The four questions this draft opened are now answered against the data — see
docs/schema-decisions.md. Their conclusions are reflected below and noted inline.

Succession — a title sold, renamed, or merged into another — is deliberately not
modelled. `django-simple-history` already records a rename, and a
self-referential link can be added when there is a real case to hang it on.
`Status.MERGED` marks the outcome without asserting a structure for it.

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

from schema.identity import identity_key  # noqa: F401  — used by rebuild_outlets

# Fields written to the public export. Named explicitly so a future column
# cannot be published by accident — see MIGRATION.md.
PUBLIC_FIELDS = (
    "id",
    "name",
    "domain",
    "canonical_url",
    "medium",
    "categories",
    "state",
    "city",
    "county",
)

# The identity rule lives in schema/identity.py so the same function is used by
# rebuild_outlets, by tests, and by anything that needs to match an outlet later.


class Medium(models.Model):
    """Controlled vocabulary. Six values carry 8,965 of the 8,977 records that
    have one: Newspaper, Television, Online, Radio, Magazine, Public Broadcasting.

    The remainder are import damage (a header row, two URLs, a call sign) or TV
    network variants that fold into Television. The network itself — NBC, CBS,
    Fox — is deliberately not modelled: twelve records do not justify a field."""

    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=64, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ("sort_order", "label")

    def __str__(self):
        return self.label


class Category(models.Model):
    """A second axis the prototype conflated with medium.

    'Ethnic Outlets' (82) and 'Network Sites' (62) appear in the same column as
    Newspaper and Radio, but describe something orthogonal: an ethnic newspaper
    is still a newspaper. One column would force a choice between recording the
    medium and recording the community served."""

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


class Owner(models.Model):
    """A publisher or chain.

    A text field cannot answer chain-level questions: the source data holds 281
    distinct ownership strings, and "Townsquare Media, Inc" and "Townsquare Media
    Inc" do not group. Consolidation is central to what the consortium studies,
    so ownership is normalised.

    `parent` allows a subsidiary to point at its group without flattening the
    distinction, which matters when a chain buys another chain rather than a
    title.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    # Casefolded and punctuation-stripped, for reconciling spelling variants
    # during import. Not shown to anyone.
    match_key = models.CharField(max_length=255, unique=True, editable=False)
    ownership_type = models.CharField(max_length=128, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="subsidiaries"
    )
    notes = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Place(models.Model):
    """A municipality, city or county that an outlet covers.

    First-class rather than buried in coverage rows, because the questions worth
    asking are aggregate ones: which outlets cover Newark, and which places are
    served by one outlet or none. The New Jersey data alone carries 4,480
    outlet-covers-place assertions across 562 municipalities, and 27 of those
    have a single outlet.

    `gnis` is the USGS identifier and the reliable join key; names collide across
    states and even within them.
    """

    class Kind(models.TextChoices):
        MUNICIPALITY = "municipality", "Municipality"
        CITY = "city", "City"
        COUNTY = "county", "County"
        REGION = "region", "Region"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.MUNICIPALITY)
    state = models.ForeignKey(
        "State", null=True, blank=True, on_delete=models.PROTECT, related_name="places"
    )
    gnis = models.CharField(max_length=64, blank=True, db_index=True)
    # New Jersey municipal identifier, present on 4,480 source rows.
    mun_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        ordering = ("state__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["name", "kind", "state"], name="uq_place_name_kind_state"
            )
        ]

    def __str__(self):
        return f"{self.name}, {self.state.code}" if self.state else self.name


class OutletPlace(models.Model):
    """One assertion that an outlet covers a place, and where it came from.

    A through model rather than a plain many-to-many so the claim keeps its
    evidence. "Who said this outlet covers Montclair" is the difference between a
    finding and an assumption.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    outlet = models.ForeignKey("Outlet", on_delete=models.CASCADE, related_name="place_links")
    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name="outlet_links")
    source_import = models.ForeignKey(
        "SourceImport", null=True, blank=True, on_delete=models.SET_NULL, related_name="place_links"
    )
    asserted_by = models.CharField(max_length=255, blank=True, help_text="source file or person")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["outlet", "place"], name="uq_outlet_place")]

    def __str__(self):
        return f"{self.outlet} covers {self.place}"


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

    # Single FK, not many-to-many. Under the corrected identity rule only 9 of
    # 2,809 outlets span states, and only four of those are genuine — border
    # towns and broadcast markets such as the La Crosse Tribune (MN/WI) and WRDW
    # (GA/SC). Four cases do not justify the ambiguity; an outlet has a home
    # state, and the breadth of what it covers is derivable from its coverage.
    state = models.ForeignKey(
        State, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )
    # City disagrees across an outlet's coverage 7% of the time, county 4%. These
    # hold the primary; the rest stays on the coverage records.
    city = models.CharField(max_length=128, blank=True)
    county = models.CharField(max_length=128, blank=True)

    owner = models.ForeignKey(
        Owner, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )

    # Places this outlet covers. The evidence for each link lives on OutletPlace.
    places = models.ManyToManyField(
        Place, through="OutletPlace", blank=True, related_name="outlets"
    )

    # Closed outlets stay in the registry and stay published, clearly marked.
    # A directory of local news that quietly drops closures hides exactly the
    # phenomenon it exists to document.
    class Status(models.TextChoices):
        OPERATING = "operating", "Operating"
        CLOSED = "closed", "Closed"
        MERGED = "merged", "Merged into another outlet"
        UNKNOWN = "unknown", "Unknown"

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPERATING, db_index=True
    )

    # Source dates are inconsistent — "2016" alongside "1/18/2019" — so each is
    # parsed where possible and the original kept either way. Never discard a
    # value because it would not parse.
    founded = models.DateField(null=True, blank=True)
    founded_raw = models.CharField(max_length=64, blank=True)
    closed_date = models.DateField(null=True, blank=True)
    closed_date_raw = models.CharField(max_length=64, blank=True)

    # Rolled up from coverage. Chosen by measuring how often an outlet's own
    # records disagree: ownership 0.4%, ownership_type 0%, newsbank 0%,
    # closed_date 1%, founded 2%. Descriptive attributes barely vary, so they
    # belong here. Sparse in the source data (ownership 832/8561, founded
    # 414/8561, closed_date 92/8561).
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
            models.Index(fields=["status", "name"]),
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

    # These stay here rather than rolling up, because they are per-observation
    # by nature and disagree within an outlet 37% and 26% of the time. mun_id and
    # gnis identify which municipality a New Jersey record covers; flattening
    # them to the outlet would destroy exactly the information they carry.
    mun_id = models.CharField(max_length=64, blank=True)
    gnis = models.CharField(max_length=64, blank=True)
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
