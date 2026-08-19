"""The registry.

Three ideas run through it:

1. CoverageRecord is ground truth. It is imported verbatim and never edited by
   derivation. Every Outlet field must be reproducible from it.
2. Identity is not the bare domain. Sharing patch.com does not make two outlets
   the same outlet — see directory/identity.py.
3. Public and admin are separated at the table level, not by column flags.
   Outlet publishes; CoverageRecord never leaves the admin.

Field-level rationale is in docs/schema-decisions.md, where every choice is
argued from the 8,561 coverage records rather than from preference.

Succession — a title sold, renamed, or merged into another — is deliberately not
modelled. simple_history already records a rename, and Status.MERGED marks the
outcome without asserting a structure for it.
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords


class Medium(models.Model):
    """Controlled vocabulary. Six values carry all but a handful of the records
    that have one: Newspaper, Television, Online, Radio, Magazine, Public
    Broadcasting.

    The remainder in the source are import damage — a header row, two URLs, a
    call sign — or TV network variants that fold into Television. The network
    itself is not modelled: twelve records do not justify a field.
    """

    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=64, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ("sort_order", "label")

    def __str__(self):
        return self.label


class Category(models.Model):
    """A second axis the prototype conflated with medium.

    'Ethnic Outlets' and 'Network Sites' appear in the same column as Newspaper
    and Radio but describe something orthogonal: an ethnic newspaper is still a
    newspaper. One column forces a choice between recording the medium and
    recording the community served.
    """

    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("label",)
        verbose_name_plural = "categories"

    def __str__(self):
        return self.label


class State(models.Model):
    """Controlled vocabulary. The source mixes 'MS' with 'Mississippi' and
    admitted a literal 'State' from a stray header row."""

    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Owner(models.Model):
    """A publisher or chain.

    A text field cannot answer chain-level questions: the source holds 281
    distinct ownership strings, and "Townsquare Media, Inc" does not group with
    "Townsquare Media Inc". Consolidation is central to what the consortium
    studies, so ownership is normalised.

    `parent` lets a subsidiary point at its group without flattening the
    distinction, which matters when a chain buys another chain rather than a
    title.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    # Casefolded and punctuation-stripped, for reconciling variants on import.
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
    """A municipality, city or county an outlet covers.

    Seeded from the USGS Domestic Names National File rather than only from
    places the coverage data mentions. A place with no outlet has no coverage
    record, so a gazetteer built from coverage can never show which places are
    served by nobody — which is most of the question.

    `gnis` is the USGS feature id and the reliable join key; names collide across
    states and within them.
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
        State, null=True, blank=True, on_delete=models.PROTECT, related_name="places"
    )
    # Arrives from the source spreadsheets as a float string ("1723212.0") and
    # must be coerced on import.
    gnis = models.CharField(max_length=64, blank=True, db_index=True)
    # New Jersey municipal identifier. Kept because it does not map cleanly onto
    # gnis: 561 gnis values and 562 mun_id values make 597 pairs, so roughly 36
    # disagree and need review.
    mun_id = models.CharField(max_length=64, blank=True, db_index=True)

    # FIPS, straight from GNIS. state_fips + county_fips is the standard 5-digit
    # county code (29 + 095 = 29095, Jackson County, Missouri) and joins this to
    # Census data at county level without any further lookup.
    state_fips = models.CharField(max_length=2, blank=True, db_index=True)
    county_fips = models.CharField(max_length=3, blank=True)
    county_name = models.CharField(max_length=128, blank=True)

    # Census GEOID, for joining place-level attributes: population, land area,
    # anything in ACS. GNIS does not carry it, but the Census Gazetteer keys on
    # ANSICODE, which *is* the GNIS feature id — so the join is exact rather
    # than a name match. Verified against the real coverage data: 505 of 561
    # ids resolve, 290 through the places file and the rest through county
    # subdivisions, because New Jersey is mostly townships.
    #
    # Left empty until something populates it. The point of recording it here is
    # that identity already carries the key, so attributes can arrive later
    # without a migration or a guess.
    census_geoid = models.CharField(max_length=16, blank=True, db_index=True)
    census_geoid_source = models.CharField(
        max_length=32, blank=True, help_text="which gazetteer file it came from"
    )

    # What GNIS called it. 'Civil' means different things by state — New Jersey
    # municipalities are Civil, while in Missouri the class is mostly land
    # surveys and planning regions — so the raw value is kept rather than
    # collapsed into `kind`.
    feature_class = models.CharField(max_length=64, blank=True)

    seeded_from_gnis = models.BooleanField(default=False)

    class Meta:
        ordering = ("state__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["name", "kind", "state"], name="uq_place_name_kind_state"
            ),
            models.UniqueConstraint(
                fields=["gnis"], condition=~models.Q(gnis=""), name="uq_place_gnis"
            ),
        ]

    def __str__(self):
        return f"{self.name}, {self.state.code}" if self.state else self.name


class SourceImport(models.Model):
    """One import run of one file. Gives every CoverageRecord a traceable origin
    and makes a bad import reversible as a unit."""

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

    Every field is editable in the admin: derivation proposes, people decide.
    `identity_key` is what makes a rerun of rebuild_outlets idempotent without
    re-merging what an editor has already split apart.
    """

    class Status(models.TextChoices):
        OPERATING = "operating", "Operating"
        CLOSED = "closed", "Closed"
        MERGED = "merged", "Merged into another outlet"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255)
    canonical_url = models.URLField(max_length=500, blank=True)

    # Registrable domain: lowercased, no scheme, no 'www.'. Indexed but NOT
    # unique — patch.com legitimately covers hundreds of distinct outlets. This
    # is the join key to the crawler; it is not an identity.
    domain = models.CharField(max_length=255, blank=True, db_index=True)
    identity_key = models.CharField(max_length=500, unique=True)

    medium = models.ForeignKey(
        Medium, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="outlets")
    owner = models.ForeignKey(
        Owner, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )
    places = models.ManyToManyField(
        Place, through="OutletPlace", blank=True, related_name="outlets"
    )

    # Single FK, not many-to-many. Under the corrected identity rule only 9 of
    # 2,809 outlets span states, and only four are genuine — border towns and
    # broadcast markets such as the La Crosse Tribune (MN/WI) and WRDW (GA/SC).
    state = models.ForeignKey(
        State, null=True, blank=True, on_delete=models.PROTECT, related_name="outlets"
    )
    # City disagrees across an outlet's coverage 7% of the time, county 4%.
    # These hold the primary; the rest stays on the coverage records.
    city = models.CharField(max_length=128, blank=True)
    county = models.CharField(max_length=128, blank=True)

    # Closed outlets stay in the registry and stay published, clearly marked. A
    # directory of local news that quietly drops closures hides exactly the
    # phenomenon it exists to document.
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPERATING, db_index=True
    )

    # Source dates are inconsistent — "2016" beside "1/18/2019" — so each is
    # parsed where possible and the original kept either way. Never discard a
    # value because it would not parse.
    founded = models.DateField(null=True, blank=True)
    founded_raw = models.CharField(max_length=64, blank=True)
    closed_date = models.DateField(null=True, blank=True)
    closed_date_raw = models.CharField(max_length=64, blank=True)

    newsbank_availability = models.CharField(max_length=128, blank=True)

    # Denormalised search blob, regenerated on save.
    search_text = models.TextField(blank=True, editable=False)

    # Rollups from CoverageRecord. record_count is the tell for a bad merge:
    # 162 records on a single Patch outlet is the signal.
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

    def build_search_text(self) -> str:
        parts = [
            self.name,
            self.domain,
            self.city,
            self.county,
            self.state.name if self.state_id else "",
            self.owner.name if self.owner_id else "",
        ]
        return " ".join(p for p in parts if p).lower()

    def save(self, *args, **kwargs):
        self.search_text = self.build_search_text()
        super().save(*args, **kwargs)


class OutletPlace(models.Model):
    """One assertion that an outlet covers a place, and where it came from.

    A through model rather than a plain many-to-many so the claim keeps its
    evidence. Who said this outlet covers Montclair is the difference between a
    finding and an assumption.

    `match_method` matters because the two routes are not equally trustworthy.
    Only New Jersey carries GNIS ids — 4,480 rows, all of them. Every other
    state has names only, so those links are inferred and default to review.
    """

    class MatchMethod(models.TextChoices):
        GNIS = "gnis", "GNIS id in the source"
        NAME = "name", "Matched on place name and state"
        MANUAL = "manual", "Set by an editor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    outlet = models.ForeignKey(Outlet, on_delete=models.CASCADE, related_name="place_links")
    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name="outlet_links")
    source_import = models.ForeignKey(
        SourceImport, null=True, blank=True, on_delete=models.SET_NULL, related_name="place_links"
    )
    asserted_by = models.CharField(max_length=255, blank=True, help_text="source file or person")
    match_method = models.CharField(
        max_length=16, choices=MatchMethod.choices, default=MatchMethod.NAME
    )
    needs_review = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["outlet", "place"], name="uq_outlet_place")]
        indexes = [models.Index(fields=["needs_review", "match_method"])]

    def __str__(self):
        return f"{self.outlet} covers {self.place}"


class CoverageRecord(models.Model):
    """One row from one source spreadsheet, preserved verbatim.

    Nothing here is normalised or corrected. Raw values are the evidence a merge
    decision is reviewed against, so they must survive intact. The `_raw` suffix
    marks fields deliberately left as free text.
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

    # The prototype's own outlet grouping, kept only so our rebuild can be
    # measured against it. Never used to group anything here — that grouping is
    # the defect being corrected.
    legacy_outlet_id = models.CharField(max_length=64, blank=True, db_index=True)

    outlet_name_raw = models.CharField(max_length=255)
    url = models.URLField(max_length=500, blank=True)
    medium_raw = models.CharField(max_length=255, blank=True)
    state_raw = models.CharField(max_length=128, blank=True)
    county = models.CharField(max_length=128, blank=True)
    city = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)

    # These stay here rather than rolling up: they are per-observation and
    # disagree within an outlet 37% and 26% of the time. mun_id and gnis
    # identify which municipality a record covers, and flattening them to the
    # outlet would destroy exactly the information they carry.
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


class DataQualityIssue(models.Model):
    """One rule violation, recorded so cleaning can be driven from the admin.

    The rules in checks/rules.py already gate publishing. Storing what they find
    turns "289 errors" from a number in a workflow log into a list someone can
    open, filter and work through.

    Rewritten wholesale on each run rather than updated in place: a violation
    that no longer occurs should disappear, and reconciling that incrementally
    is more code than deleting and reinserting a few hundred rows.
    """

    class Severity(models.TextChoices):
        ERROR = "error", "Error — blocks publishing"
        WARN = "warn", "Warning"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=8, choices=Severity.choices, db_index=True)
    message = models.TextField()
    outlet = models.ForeignKey(
        "Outlet", null=True, blank=True, on_delete=models.CASCADE, related_name="issues"
    )
    row_id = models.CharField(max_length=64, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("severity", "rule")
        indexes = [models.Index(fields=["severity", "rule"])]
        verbose_name = "data quality issue"

    def __str__(self):
        return f"{self.rule}: {self.message[:60]}"


class Collection(models.Model):
    """A named subset of the registry, and the unit handed to the crawler: the
    slug becomes a crawler dataset slug and each Outlet id lands in
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
