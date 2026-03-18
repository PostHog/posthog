from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.desktop_recordings.backend.models import DesktopRecording


class DesktopRecordingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "meeting_title",
        "platform",
        "status",
        "team_link",
        "created_by_link",
        "started_at",
        "duration_seconds",
    )
    list_filter = ("status", "platform", "started_at", "created_at")
    search_fields = ("id", "meeting_title", "meeting_url", "team__name", "created_by__email")
    readonly_fields = (
        "id",
        "sdk_upload_id",
        "recall_recording_id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "summary_generated_at",
        "tasks_generated_at",
    )
    autocomplete_fields = ("team", "created_by")

    fieldsets = (
        (None, {"fields": ("id", "team", "created_by", "status")}),
        (
            "Meeting info",
            {
                "fields": (
                    "platform",
                    "meeting_title",
                    "meeting_url",
                    "duration_seconds",
                    "participants",
                )
            },
        ),
        (
            "Recording details",
            {
                "fields": (
                    "sdk_upload_id",
                    "recall_recording_id",
                    "video_url",
                    "video_size_bytes",
                    "notes",
                    "error_message",
                )
            },
        ),
        (
            "Transcript & AI",
            {
                "fields": (
                    "transcript_text",
                    "transcript_segments",
                    "summary",
                    "summary_generated_at",
                    "extracted_tasks",
                    "tasks_generated_at",
                )
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "started_at",
                    "completed_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Team")
    def team_link(self, obj: DesktopRecording):
        if obj.team:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_team_change", args=[obj.team.pk]),
                obj.team.name,
            )
        return "-"

    @admin.display(description="Created by")
    def created_by_link(self, obj: DesktopRecording):
        if obj.created_by:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_user_change", args=[obj.created_by.pk]),
                obj.created_by.email,
            )
        return "-"
