from django.contrib import admin
from django.http import HttpRequest

from products.replay_vision.backend.models import ReplayObservation, ReplayScanner, VisionAction, VisionActionRun


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


@admin.register(VisionAction)
class VisionActionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "team",
        "scanner",
        "trigger_type",
        "mode",
        "enabled",
        "max_observations",
        "next_run_at",
        "created_at",
    )
    list_select_related = ("team", "scanner")
    list_filter = ("trigger_type", "mode", "enabled")
    search_fields = ("name",)
    raw_id_fields = ("team", "scanner", "hog_flow", "created_by")
    readonly_fields = ("id", "next_run_at", "last_run_at", "created_at", "updated_at")


@admin.register(VisionActionRun)
class VisionActionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "vision_action", "team", "status", "observation_count", "scheduled_at", "created_at")
    list_select_related = ("vision_action", "team")
    list_filter = ("status",)
    search_fields = ("idempotency_key", "temporal_workflow_id")
    raw_id_fields = ("vision_action", "team")
    readonly_fields = (
        "id",
        "vision_action",
        "team",
        "temporal_workflow_id",
        "idempotency_key",
        "scheduled_at",
        "status",
        "synthesized_markdown",
        "output",
        "observation_count",
        "error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Created by the vision-action workflow, never via admin.
        return False
