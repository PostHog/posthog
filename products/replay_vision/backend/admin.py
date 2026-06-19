from datetime import UTC, datetime
from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from products.replay_vision.backend.models import (
    ReplayObservation,
    ReplayQuotaGrant,
    ReplayScanner,
    VisionAction,
    VisionActionRun,
)
from products.replay_vision.backend.quota import next_month_start


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


@admin.register(ReplayQuotaGrant)
class ReplayQuotaGrantAdmin(admin.ModelAdmin):
    list_display = ("organization", "amount", "granted_at", "expires_at", "granted_by", "reason")
    list_filter = ("granted_at", "expires_at")
    search_fields = ("organization__name", "reason")
    raw_id_fields = ("organization", "granted_by")
    readonly_fields = ("id", "granted_at")

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        initial: dict[str, Any] = super().get_changeform_initial_data(request)
        # Pre-fill but don't force — admins can clear either field on the add form.
        # Pass native types (not strings): the admin's SplitDateTimeWidget calls
        # `to_current_timezone(value)` on initial, which AttributeErrors on a str.
        initial.setdefault("expires_at", next_month_start(datetime.now(UTC)))
        initial.setdefault("granted_by", request.user.pk)
        return initial


@admin.register(VisionAction)
class VisionActionAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "scanner", "trigger_type", "mode", "enabled", "next_run_at", "created_at")
    list_filter = ("trigger_type", "mode", "enabled")
    search_fields = ("name",)
    raw_id_fields = ("team", "scanner", "hog_flow", "created_by")
    readonly_fields = ("id", "next_run_at", "last_run_at", "created_at", "updated_at")


@admin.register(VisionActionRun)
class VisionActionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "vision_action", "team", "status", "observation_count", "scheduled_at", "created_at")
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
