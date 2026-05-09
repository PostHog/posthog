from django.contrib import admin
from django.http import HttpRequest

from products.replay_vision.backend.models import ReplayLens, ReplayLensObservation


@admin.register(ReplayLens)
class ReplayLensAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "lens_type", "status", "is_builtin", "emits_signals", "created_at")
    list_filter = ("lens_type", "status", "is_builtin", "emits_signals")
    search_fields = ("name", "description")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "last_swept_at", "lens_version")


@admin.register(ReplayLensObservation)
class ReplayLensObservationAdmin(admin.ModelAdmin):
    list_display = ("lens", "session_id", "status", "triggered_by", "created_at", "completed_at")
    list_filter = ("status", "triggered_by")
    search_fields = ("session_id", "workflow_id")
    # Observations are workflow-created and immutable post-create except for status/error_reason.
    readonly_fields = (
        "id",
        "lens",
        "team",
        "session_id",
        "triggered_by",
        "triggered_by_user",
        "lens_version",
        "lens_config_snapshot",
        "model_used",
        "provider_used",
        "workflow_id",
        "started_at",
        "completed_at",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Created by workflow/consumer, never via admin.
        return False
