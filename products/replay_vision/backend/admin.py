from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from products.replay_vision.backend.models import (
    ReplayObservation,
    ReplayObservationMedia,
    ReplayScanner,
    ReplayVisionLearnedRuleset,
)


@admin.register(ReplayScanner)
class ReplayScannerAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "scanner_type", "enabled", "emits_signals", "created_at")
    list_filter = ("scanner_type", "enabled", "emits_signals")
    search_fields = ("name", "description")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "last_swept_at", "scanner_version")


@admin.register(ReplayObservation)
class ReplayObservationAdmin(admin.ModelAdmin):
    list_display = ("scanner", "session_id", "status", "triggered_by", "created_at", "completed_at")
    # The product's largest table: without this the changelist runs a query per row for the FK columns.
    list_select_related = ("scanner", "team")
    list_filter = ("status", "triggered_by")
    search_fields = ("session_id", "workflow_id")
    # Observations are workflow-created and immutable post-create except for status/error_reason.
    readonly_fields = (
        "id",
        "scanner",
        "team",
        "session_id",
        "triggered_by",
        "triggered_by_user",
        "backfill",
        "scanner_snapshot",
        "scanner_result",
        "workflow_id",
        "started_at",
        "completed_at",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Created by workflow/consumer, never via admin.
        return False


@admin.register(ReplayObservationMedia)
class ReplayObservationMediaAdmin(admin.ModelAdmin):
    list_display = ("observation", "kind", "position", "created_at")
    list_select_related = ("observation", "team")
    list_filter = ("kind",)
    # raw_id_fields, not the default select: each of these targets a table too large to enumerate per row.
    raw_id_fields = ("observation", "asset", "team")
    readonly_fields = ("id", "created_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Written by the media workflow, never via admin.
        return False


@admin.register(ReplayVisionLearnedRuleset)
class ReplayVisionLearnedRulesetAdmin(admin.ModelAdmin):
    """Read-only: users never see these rules, so this is the only place staff can check what a team's
    ratings taught its scanners."""

    list_display = ("team", "scanner", "version", "created_at")
    list_select_related = ("team", "scanner")
    raw_id_fields = ("team", "scanner")
    readonly_fields = ("id", "team", "scanner", "version", "rules", "model", "trace_id", "created_at")
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[ReplayVisionLearnedRuleset]:
        # Staff browse across teams; the default manager fails closed without a team context.
        return ReplayVisionLearnedRuleset.objects.unscoped().select_related("team", "scanner")

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Written by the learned rules job, never via admin.
        return False

    def has_change_permission(self, request: HttpRequest, obj: ReplayVisionLearnedRuleset | None = None) -> bool:
        return False
