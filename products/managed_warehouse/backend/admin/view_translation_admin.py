from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.safestring import SafeString

from posthog.admin.console.moved import MovedToConsole

from products.managed_warehouse.backend.models import (
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)


# Starting and retrying jobs live on the Managed warehouse panel in PostHog Admin. The add URL redirects there.
@admin.register(ManagedWarehouseViewTranslationJob)
class ManagedWarehouseViewTranslationJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization_id",
        "status",
        "trigger_source",
        "scope",
        "total_count",
        "compiled_count",
        "failed_count",
        "stale_count",
        "created_at",
        "finished_at",
    )
    list_filter = ("status", "trigger_source", "scope")
    search_fields = ("=id", "=organization__id", "=retry_of__id", "workflow_id", "workflow_run_id")
    raw_id_fields = ("organization", "created_by", "retry_of")
    ordering = ("-created_at",)
    fields = (
        "id",
        "posthog_admin",
        "organization",
        "created_by",
        "trigger_source",
        "scope",
        "selected_saved_query_ids",
        "retry_of",
        "status",
        "workflow_id",
        "workflow_run_id",
        "started_at",
        "finished_at",
        "total_count",
        "compiled_count",
        "failed_count",
        "stale_count",
        "latest_error",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    @admin.display(description="PostHog Admin")
    def posthog_admin(self, obj: ManagedWarehouseViewTranslationJob) -> SafeString:
        return MovedToConsole.action("organization", obj.organization, "managed-warehouse", "Start or retry a job")

    def has_delete_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationJob | None = None
    ) -> bool:
        return False


@admin.register(ManagedWarehouseViewTranslationResult)
class ManagedWarehouseViewTranslationResultAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "job_id",
        "team_id",
        "saved_query_name",
        "is_materialized",
        "status",
        "processed_at",
    )
    list_filter = ("status", "is_materialized")
    search_fields = ("=id", "=job__id", "=team__id", "=saved_query_id", "saved_query_name")
    raw_id_fields = ("job", "team")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "posthog_admin",
        "job",
        "team",
        "saved_query_id",
        "saved_query_name",
        "is_materialized",
        "source_query_hash",
        "status",
        "trino_sql",
        "trino_values",
        "normalized_hogql",
        "error_type",
        "error_message",
        "processed_at",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[ManagedWarehouseViewTranslationResult]:
        return ManagedWarehouseViewTranslationResult.all_teams.select_related("job__organization", "team")

    @admin.display(description="PostHog Admin")
    def posthog_admin(self, obj: ManagedWarehouseViewTranslationResult) -> SafeString:
        return MovedToConsole.action("organization", obj.job.organization, "managed-warehouse", "Retry translations")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationResult | None = None
    ) -> bool:
        return False

    def has_view_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationResult | None = None
    ) -> bool:
        return True

    def has_delete_permission(
        self, request: HttpRequest, obj: ManagedWarehouseViewTranslationResult | None = None
    ) -> bool:
        return False
