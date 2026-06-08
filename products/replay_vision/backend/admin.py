from datetime import UTC, datetime
from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from dateutil.relativedelta import relativedelta

from posthog.date_util import start_of_month

from products.replay_vision.backend.models import ReplayObservation, ReplayQuotaGrant, ReplayScanner


def _default_grant_expiry() -> datetime:
    """First moment of next month (UTC) — matches `compute_quota_snapshot`'s period boundary."""
    return start_of_month(datetime.now(UTC)) + relativedelta(months=1)


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
        initial = super().get_changeform_initial_data(request)
        # Pre-fill but don't force — admins can clear either field on the add form.
        initial.setdefault("expires_at", _default_grant_expiry())
        initial.setdefault("granted_by", request.user.pk)
        return initial
