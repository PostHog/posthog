from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.notifications.backend.models import NotificationEvent


class NotificationEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "notification_type",
        "priority",
        "title",
        "team_link",
        "target_type",
        "target_id",
        "created_at",
    )
    list_filter = ("notification_type", "priority", "target_type", "created_at")
    search_fields = ("id", "title", "body", "target_id", "resource_id", "source_id")
    readonly_fields = (
        "id",
        "organization",
        "team",
        "target_type",
        "target_id",
        "resolved_user_ids",
        "created_at",
    )
    autocomplete_fields = ()
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "notification_type",
                    "priority",
                    "title",
                    "body",
                )
            },
        ),
        (
            "Targeting",
            {
                "fields": (
                    "organization",
                    "team",
                    "target_type",
                    "target_id",
                    "resolved_user_ids",
                )
            },
        ),
        (
            "Resource",
            {
                "fields": (
                    "resource_type",
                    "resource_id",
                    "source_url",
                    "source_type",
                    "source_id",
                )
            },
        ),
        ("Dates", {"fields": ("created_at",)}),
    )

    def team_link(self, obj: NotificationEvent) -> str:
        if not obj.team_id:
            return "–"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[obj.team_id]),
            obj.team.name if obj.team else obj.team_id,
        )
