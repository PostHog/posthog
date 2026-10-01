import json

from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html

from .models import DailyBriefing


def _pretty(value: object) -> str:
    return format_html("<pre style='white-space: pre-wrap'>{}</pre>", json.dumps(value, indent=2, ensure_ascii=False))


@admin.register(DailyBriefing)
class DailyBriefingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_id",
        "user_id",
        "local_day",
        "trigger",
        "status",
        "writer",
        "created_at",
        "ready_at",
    )
    list_display_links = ("id",)
    list_filter = ("status", "writer", "trigger", "local_day")
    search_fields = ("id", "team_id", "user_id")
    ordering = ("-created_at",)
    fields = (
        "id",
        "team_id",
        "user_id",
        "local_day",
        "timezone",
        "trigger",
        "status",
        "writer",
        "error",
        "created_at",
        "ready_at",
        "last_viewed_at",
        "facts_pretty",
        "content_pretty",
    )
    readonly_fields = fields

    @admin.display(description="Facts")
    def facts_pretty(self, obj: DailyBriefing) -> str:
        return _pretty(obj.facts)

    @admin.display(description="Content")
    def content_pretty(self, obj: DailyBriefing) -> str:
        return _pretty(obj.content)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: DailyBriefing | None = None) -> bool:
        return False
