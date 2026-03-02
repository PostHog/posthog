import json

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.endpoints.backend.models import Endpoint, EndpointVersion


class EndpointVersionInline(admin.TabularInline):
    model = EndpointVersion
    extra = 0
    can_delete = False
    show_change_link = True
    ordering = ("-version",)
    fields = (
        "version",
        "is_active",
        "query_kind",
        "cache_age_seconds",
        "is_materialized_display",
        "saved_query_name",
        "saved_query_status",
        "saved_query_error_preview",
        "created_at",
        "created_by",
    )
    readonly_fields = fields

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("saved_query", "saved_query__table", "created_by")

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Query kind")
    def query_kind(self, obj: EndpointVersion) -> str:
        if obj.query:
            return obj.query.get("kind") or "—"
        return "—"

    @admin.display(description="Materialized", boolean=True)
    def is_materialized_display(self, obj: EndpointVersion) -> bool:
        return obj.is_materialized

    @admin.display(description="Saved query")
    def saved_query_name(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query:
            sq = obj.saved_query
            if sq.table_id:
                url = reverse("admin:data_warehouse_datawarehousetable_change", args=[sq.table_id])
                return format_html('<a href="{}">{}</a>', url, sq.name)
            return str(sq.name)
        if obj.saved_query_id:
            return str(obj.saved_query_id)
        return "—"

    @admin.display(description="Saved query status")
    def saved_query_status(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query:
            return obj.saved_query.status or "—"
        return "—"

    @admin.display(description="Saved query error")
    def saved_query_error_preview(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query and obj.saved_query.latest_error:
            error = obj.saved_query.latest_error
            return (error[:200] + "…") if len(error) > 200 else error
        return "—"


class EndpointAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "is_active",
        "deleted",
        "current_version",
        "versions_count",
        "last_executed_at",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_filter = ("is_active", "deleted")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("team", "team__organization", "created_by")

    readonly_fields = (
        "id",
        "name",
        "team",
        "current_version",
        "created_by",
        "created_at",
        "updated_at",
        "last_executed_at",
        "deleted",
        "deleted_at",
        "derived_from_insight",
        "endpoint_path_display",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "name",
                    "team",
                    "is_active",
                    "current_version",
                    "derived_from_insight",
                    "endpoint_path_display",
                )
            },
        ),
        (
            "Dates",
            {"fields": ("created_at", "updated_at", "last_executed_at", "created_by", "deleted", "deleted_at")},
        ),
    )

    inlines = [EndpointVersionInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Team")
    def team_link(self, obj: Endpoint):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[obj.team_id]),
            obj.team.name,
        )

    @admin.display(description="Versions")
    def versions_count(self, obj: Endpoint) -> int:
        return obj.versions.count()

    @admin.display(description="Endpoint path")
    def endpoint_path_display(self, obj: Endpoint) -> str:
        return obj.endpoint_path


class EndpointVersionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "endpoint_link",
        "version",
        "is_active",
        "query_kind",
        "is_materialized_display",
        "saved_query_name",
        "saved_query_status",
        "saved_query_error_preview",
        "cache_age_seconds",
        "created_at",
    )
    list_display_links = ("id",)
    search_fields = (
        "id",
        "endpoint__name",
        "endpoint__team__name",
        "endpoint__id",
        "saved_query__name",
    )
    list_filter = ("is_active",)
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("endpoint", "endpoint__team", "saved_query", "created_by")

    readonly_fields = (
        "id",
        "endpoint",
        "version",
        "cache_age_seconds",
        "created_at",
        "created_by",
        "query_pretty",
        "saved_query_name",
        "saved_query_status",
        "saved_query_error_full",
        "is_materialized_display",
        "columns_pretty",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "endpoint",
                    "version",
                    "is_active",
                    "cache_age_seconds",
                    "query_pretty",
                    "columns_pretty",
                    "created_at",
                    "created_by",
                )
            },
        ),
        (
            "Materialization",
            {
                "fields": (
                    "is_materialized_display",
                    "saved_query_name",
                    "saved_query_status",
                    "saved_query_error_full",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("endpoint", "endpoint__team", "saved_query", "saved_query__table", "created_by")
        )

    @admin.display(description="Endpoint")
    def endpoint_link(self, obj: EndpointVersion):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:endpoints_endpoint_change", args=[obj.endpoint_id]),
            str(obj.endpoint),
        )

    @admin.display(description="Query kind")
    def query_kind(self, obj: EndpointVersion) -> str:
        if obj.query:
            return obj.query.get("kind") or "—"
        return "—"

    @admin.display(description="Materialized", boolean=True)
    def is_materialized_display(self, obj: EndpointVersion) -> bool:
        return obj.is_materialized

    @admin.display(description="Saved query")
    def saved_query_name(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query:
            sq = obj.saved_query
            if sq.table_id:
                url = reverse("admin:data_warehouse_datawarehousetable_change", args=[sq.table_id])
                return format_html('<a href="{}">{}</a>', url, sq.name)
            return str(sq.name)
        if obj.saved_query_id:
            return str(obj.saved_query_id)
        return "—"

    @admin.display(description="Saved query status")
    def saved_query_status(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query:
            return obj.saved_query.status or "—"
        return "—"

    @admin.display(description="Saved query error")
    def saved_query_error_preview(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query and obj.saved_query.latest_error:
            error = obj.saved_query.latest_error
            return (error[:200] + "…") if len(error) > 200 else error
        return "—"

    @admin.display(description="Saved query error (full)")
    def saved_query_error_full(self, obj: EndpointVersion) -> str:
        if obj.saved_query_id and obj.saved_query and obj.saved_query.latest_error:
            return obj.saved_query.latest_error
        return "—"

    @admin.display(description="Query")
    def query_pretty(self, obj: EndpointVersion) -> str:
        if obj.query:
            return format_html("<pre>{}</pre>", json.dumps(obj.query, indent=2))
        return "—"

    @admin.display(description="Columns")
    def columns_pretty(self, obj: EndpointVersion) -> str:
        if obj.columns:
            return format_html("<pre>{}</pre>", json.dumps(obj.columns, indent=2))
        return "—"
