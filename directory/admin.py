"""The admin is most of the application.

The work it exists for is the review queue: 222 outlets inherited from the
prototype each cover more than one real outlet, because the old dedupe keyed on
the bare domain. Fixing that means looking at an outlet's coverage rows and
deciding whether they are one masthead or several — so the coverage inline and
the split action are the centre of this file, not decoration.
"""

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count
from import_export.admin import ImportExportModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from directory import dashboard
from directory.identity import identity_key, registrable_domain, slugify
from directory.models import (
    Category,
    Collection,
    CoverageRecord,
    DataQualityIssue,
    Medium,
    Outlet,
    OutletPlace,
    Owner,
    Place,
    SourceImport,
    State,
)
from directory.publishing import PublishError, request_publish


def _dashboard_index(request, extra_context=None):
    """Put the review summary on the admin index.

    Patching the default site rather than substituting a custom AdminSite:
    every ModelAdmin here registers against the default, and swapping the site
    would mean re-registering all of them and rewriting every /admin/ URL that
    already exists in links and bookmarks.
    """
    latest = DataQualityIssue.objects.order_by("-detected_at").first()
    return _original_index(
        request,
        {
            **(extra_context or {}),
            "review_tiles": dashboard.review_tiles(),
            "quality_tiles": dashboard.quality_tiles(),
            "registry_tiles": dashboard.registry_tiles(),
            "unserved": dashboard.unserved_places(),
            "quality_checked": latest.detected_at if latest else None,
        },
    )


_original_index = admin.site.index
admin.site.index = _dashboard_index


class DistinctNameFilter(admin.SimpleListFilter):
    """How many different mastheads an outlet's coverage rows name.

    This is the merge signal. Record count is not: an outlet legitimately has
    hundreds of coverage rows when a study lists it once per municipality.
    """

    title = "distinct names in coverage"
    parameter_name = "distinct_names"

    def lookups(self, request, model_admin):
        return [("1", "One — consistent"), ("2", "Two or more — suspected bad merge")]

    def queryset(self, request, queryset):
        if self.value() not in {"1", "2"}:
            return queryset
        annotated = queryset.annotate(n=Count("coverage__outlet_name_raw", distinct=True))
        return annotated.filter(n__lte=1) if self.value() == "1" else annotated.filter(n__gt=1)


class CoverageInline(admin.TabularInline):
    """The evidence, on the outlet's own page.

    Without this, reviewing a merge means opening another screen and holding two
    lists in your head.
    """

    model = CoverageRecord
    extra = 0
    can_delete = False
    fields = ("outlet_name_raw", "url", "state_raw", "county", "city", "source_file")
    readonly_fields = fields
    ordering = ("outlet_name_raw",)
    show_change_link = True
    verbose_name_plural = "Coverage records (source evidence — not editable here)"

    def has_add_permission(self, request, obj=None):
        return False


class OutletPlaceInline(admin.TabularInline):
    model = OutletPlace
    extra = 0
    autocomplete_fields = ("place",)
    fields = ("place", "match_method", "needs_review", "asserted_by")


@admin.register(Outlet)
class OutletAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    list_display = (
        "name",
        "domain",
        "medium",
        "state",
        "city",
        "status",
        "record_count",
        "distinct_names",
        "needs_review",
    )
    list_filter = (
        "needs_review",
        "status",
        "is_published",
        DistinctNameFilter,
        "medium",
        "state",
        "categories",
    )
    search_fields = ("name", "domain", "canonical_url", "city", "county", "search_text")
    autocomplete_fields = ("owner", "medium", "state")
    filter_horizontal = ("categories",)
    inlines = (OutletPlaceInline, CoverageInline)
    readonly_fields = ("identity_key", "record_count", "source_count", "created_at", "updated_at")
    list_select_related = ("medium", "state", "owner")
    actions = (
        "split_by_name",
        "merge_selected",
        "mark_reviewed",
        "flag_for_review",
        "publish_feed",
    )
    fieldsets = (
        (None, {"fields": ("name", "canonical_url", "domain", "identity_key", "status")}),
        ("Classification", {"fields": ("medium", "categories", "owner")}),
        ("Location", {"fields": ("state", "city", "county")}),
        ("Dates", {"fields": (("founded", "founded_raw"), ("closed_date", "closed_date_raw"))}),
        ("Review", {"fields": ("needs_review", "review_note", "is_published")}),
        (
            "Derived",
            {
                "classes": ("collapse",),
                "fields": (
                    "record_count",
                    "source_count",
                    "newsbank_availability",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    @admin.display(description="names", ordering="n")
    def distinct_names(self, obj):
        return getattr(obj, "n", None) or obj.coverage.values("outlet_name_raw").distinct().count()

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(n=Count("coverage__outlet_name_raw", distinct=True))

    @admin.action(description="Split: one outlet per distinct name in coverage")
    def split_by_name(self, request, queryset):
        """Undo a bad merge.

        The original keeps the most common name and its identity key, so links to
        it stay valid. Every other name becomes a new outlet carrying its own
        coverage rows. Nothing is deleted — a split is reversible by merging back.
        """
        created = skipped = 0
        with transaction.atomic():
            for outlet in queryset.prefetch_related("coverage"):
                groups: dict[str, list[CoverageRecord]] = {}
                for record in outlet.coverage.all():
                    groups.setdefault(record.outlet_name_raw.strip(), []).append(record)

                if len(groups) < 2:
                    skipped += 1
                    continue

                # Keep the name with the most evidence behind it.
                ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
                for name, records in ordered[1:]:
                    first = records[0]
                    key = identity_key(first.url, name, first.state_raw) or (
                        f"split:{slugify(name)}|{outlet.identity_key}"
                    )
                    if Outlet.objects.filter(identity_key=key).exists():
                        key = f"{key}|{slugify(name)}"

                    new = Outlet.objects.create(
                        name=name,
                        canonical_url=first.url or "",
                        domain=registrable_domain(first.url) if first.url else "",
                        identity_key=key,
                        state=outlet.state,
                        city=first.city or "",
                        county=first.county or "",
                        medium=outlet.medium,
                        owner=outlet.owner,
                        needs_review=True,
                        review_note=f"Split from {outlet.name}",
                        record_count=len(records),
                    )
                    CoverageRecord.objects.filter(pk__in=[r.pk for r in records]).update(outlet=new)
                    created += 1

                outlet.name = ordered[0][0] or outlet.name
                outlet.record_count = len(ordered[0][1])
                outlet.needs_review = False
                outlet.review_note = f"Split into {len(ordered)} outlets"
                outlet.save()

        if created:
            self.message_user(request, f"Created {created} outlet(s) from split.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"{skipped} outlet(s) had one name and were left alone.",
                messages.INFO,
            )

    @admin.action(description="Merge: fold the selected outlets into the oldest")
    def merge_selected(self, request, queryset):
        """Combine outlets that are one masthead recorded several ways.

        The counterpart to splitting. Reviewing a bad merge often means
        splitting it and then recombining the pieces that were the same paper
        written differently, and without this that means reassigning coverage
        records by hand.

        The survivor is the earliest-created outlet, so repeating the action on
        the same selection is stable. Coverage moves rather than being copied,
        and the absorbed outlets are deleted only after their evidence has been
        reassigned — a merge loses nothing.
        """
        outlets = list(queryset.order_by("created_at"))
        if len(outlets) < 2:
            self.message_user(request, "Select two or more outlets to merge.", messages.WARNING)
            return

        survivor, absorbed = outlets[0], outlets[1:]
        moved = 0
        with transaction.atomic():
            for other in absorbed:
                moved += CoverageRecord.objects.filter(outlet=other).update(outlet=survivor)
                OutletPlace.objects.filter(outlet=other).exclude(
                    place__in=survivor.places.all()
                ).update(outlet=survivor)
                other.delete()

            survivor.record_count = survivor.coverage.count()
            survivor.source_count = survivor.coverage.values("source_file").distinct().count()
            survivor.needs_review = False
            survivor.review_note = f"Merged {len(absorbed)} outlet(s) in: " + ", ".join(
                o.name for o in absorbed
            )
            survivor.save()

        self.message_user(
            request,
            f"Merged {len(absorbed)} outlet(s) into {survivor.name}; "
            f"{moved} coverage record(s) moved.",
            messages.SUCCESS,
        )

    @admin.action(description="Publish the public feed now")
    def publish_feed(self, request, queryset):
        """Ask GitHub to rebuild the feed.

        Deliberately an explicit action rather than something that fires on
        every save: an editor part-way through fixing a merge should not be
        publishing each intermediate state, and being told when it happened is
        worth more than it happening silently.

        The selection is ignored — the feed is always the whole registry.
        """
        try:
            request_publish(reason=f"admin:{request.user.get_username()}")
        except PublishError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            return
        self.message_user(
            request,
            "Publish requested. The feed updates in a few minutes; progress is on the Actions tab.",
            messages.SUCCESS,
        )

    @admin.action(description="Mark reviewed")
    def mark_reviewed(self, request, queryset):
        n = queryset.update(needs_review=False)
        self.message_user(request, f"{n} marked reviewed.", messages.SUCCESS)

    @admin.action(description="Flag for review")
    def flag_for_review(self, request, queryset):
        n = queryset.update(needs_review=True)
        self.message_user(request, f"{n} flagged.", messages.SUCCESS)


@admin.register(CoverageRecord)
class CoverageRecordAdmin(ImportExportModelAdmin):
    list_display = ("outlet_name_raw", "outlet", "state_raw", "city", "source_file")
    list_filter = ("source_file", "state_raw")
    search_fields = ("outlet_name_raw", "url", "city", "county", "notes")
    autocomplete_fields = ("outlet",)
    list_select_related = ("outlet",)

    def has_change_permission(self, request, obj=None):
        """Source rows are evidence. Reassigning one to a different outlet is a
        curation decision made through the outlet, not an edit of the record."""
        return False


@admin.register(Owner)
class OwnerAdmin(SimpleHistoryAdmin):
    list_display = ("name", "ownership_type", "parent", "outlet_count")
    search_fields = ("name",)
    autocomplete_fields = ("parent",)
    readonly_fields = ("match_key",)

    @admin.display(description="outlets")
    def outlet_count(self, obj):
        return obj.outlets.count()

    def save_model(self, request, obj, form, change):
        obj.match_key = slugify(obj.name)
        super().save_model(request, obj, form, change)


class ServedFilter(admin.SimpleListFilter):
    """How many outlets cover a place.

    The reason for seeding the gazetteer: a place with no outlet has no coverage
    record, so "served by nobody" is only answerable against a table that
    contains places nothing points at.
    """

    title = "outlets covering it"
    parameter_name = "served"

    def lookups(self, request, model_admin):
        return [("none", "None"), ("one", "Exactly one"), ("many", "Two or more")]

    def queryset(self, request, queryset):
        if self.value() not in {"none", "one", "many"}:
            return queryset
        annotated = queryset.annotate(n=Count("outlets", distinct=True))
        return {
            "none": annotated.filter(n=0),
            "one": annotated.filter(n=1),
            "many": annotated.filter(n__gt=1),
        }[self.value()]


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    # 231,389 rows. Faceted counts and unindexed search would make the
    # changelist unusable, so search is restricted to indexed columns.
    show_facets = admin.ShowFacets.NEVER
    list_display = ("name", "kind", "feature_class", "state", "gnis", "outlet_count")
    list_filter = (ServedFilter, "feature_class", "kind", "state", "seeded_from_gnis")
    search_fields = ("name", "gnis", "mun_id")
    list_select_related = ("state",)

    def get_queryset(self, request):
        # Annotated once here rather than queried per row: 231,389 rows would
        # otherwise mean a count query for every line on the page.
        return super().get_queryset(request).annotate(n=Count("outlets", distinct=True))

    @admin.display(description="outlets", ordering="n")
    def outlet_count(self, obj):
        return obj.n


@admin.register(Collection)
class CollectionAdmin(SimpleHistoryAdmin):
    list_display = ("label", "slug", "outlet_count", "created_at")
    prepopulated_fields = {"slug": ("label",)}
    filter_horizontal = ("outlets",)
    search_fields = ("label", "slug")

    @admin.display(description="outlets")
    def outlet_count(self, obj):
        return obj.outlets.count()


@admin.register(SourceImport)
class SourceImportAdmin(admin.ModelAdmin):
    list_display = ("filename", "sheet", "row_count", "imported_by", "imported_at")
    readonly_fields = ("imported_at",)
    search_fields = ("filename",)


@admin.register(Medium)
class MediumAdmin(admin.ModelAdmin):
    list_display = ("label", "slug", "sort_order")
    prepopulated_fields = {"slug": ("label",)}
    search_fields = ("label",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("label", "slug")
    prepopulated_fields = {"slug": ("label",)}
    search_fields = ("label",)


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(DataQualityIssue)
class DataQualityIssueAdmin(admin.ModelAdmin):
    """What the rules found, so cleaning is driven by the same checks that gate
    publishing rather than by memory."""

    list_display = ("rule", "severity", "message", "outlet", "detected_at")
    list_filter = ("severity", "rule")
    search_fields = ("message", "row_id", "outlet__name")
    list_select_related = ("outlet",)
    readonly_fields = ("rule", "severity", "message", "outlet", "row_id", "detected_at")

    def has_add_permission(self, request):
        # Written by check_data. Adding one by hand would be a note, not a finding.
        return False


@admin.register(OutletPlace)
class OutletPlaceAdmin(admin.ModelAdmin):
    """Place links, so the ones inferred from a name can be confirmed.

    Only New Jersey carries GNIS ids; every other link was matched on text and
    is a guess until someone looks.
    """

    list_display = ("outlet", "place", "match_method", "needs_review", "asserted_by")
    list_filter = ("match_method", "needs_review")
    search_fields = ("outlet__name", "place__name")
    autocomplete_fields = ("outlet", "place")
    list_select_related = ("outlet", "place")
    actions = ("confirm_links",)

    @admin.action(description="Confirm: these places are correct")
    def confirm_links(self, request, queryset):
        n = queryset.update(needs_review=False, match_method=OutletPlace.MatchMethod.MANUAL)
        self.message_user(request, f"{n} link(s) confirmed.", messages.SUCCESS)
