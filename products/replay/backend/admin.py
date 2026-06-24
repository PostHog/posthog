from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from products.replay.backend.models.exported_recording import ExportedRecording

_STATUS_COLORS = {
    ExportedRecording.Status.COMPLETE: "green",
    ExportedRecording.Status.FAILED: "red",
    ExportedRecording.Status.RUNNING: "blue",
    ExportedRecording.Status.PENDING: "orange",
}


@admin.register(ExportedRecording)
class ExportedRecordingAdmin(admin.ModelAdmin):
    list_display = ("session_id", "team_link", "status_display", "created_by", "created_at", "download_link")
    list_filter = ("status", "created_at")
    search_fields = ("session_id", "team__name", "team__id", "reason")
    raw_id_fields = ("team", "created_by")
    readonly_fields = (
        "id",
        "team",
        "session_id",
        "reason",
        "export_location",
        "status",
        "error_message",
        "created_by",
        "created_at",
    )

    @admin.display(description="Team", ordering="team")
    def team_link(self, obj: ExportedRecording) -> str:
        url = reverse("admin:posthog_team_change", args=[obj.team_id])
        return format_html('<a href="{}">{}</a>', url, obj.team)

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj: ExportedRecording) -> str:
        if obj.is_expired:
            return format_html('<span style="color: gray;">Expired</span>')
        color = _STATUS_COLORS.get(ExportedRecording.Status(obj.status), "black")
        return format_html('<span style="color: {};">{}</span>', color, obj.get_status_display())

    @admin.display(description="Download")
    def download_link(self, obj: ExportedRecording) -> str:
        if obj.is_expired or not obj.export_location:
            return "-"
        # Reuse the per-team download view, which streams the file from S3.
        url = reverse("admin:posthog_team_download_export", args=[obj.team_id, obj.id])
        return format_html('<a class="button" href="{}">Download</a>', url)

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Exports are created by the recording-export workflow, never via admin.
        return False
