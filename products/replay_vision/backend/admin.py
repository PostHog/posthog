from django.contrib import admin
from django.http import HttpRequest

from products.replay_vision.backend.models import ReplayObservation, ReplayScanner


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
