from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from products.notifications.backend.models import AgentNotice


@admin.register(AgentNotice)
class AgentNoticeAdmin(admin.ModelAdmin):
    list_display = (
        "message_preview",
        "team_link",
        "feature_flag",
        "starts_at",
        "expires_at",
        "is_active",
        "created_by",
    )
    list_filter = ("is_active", "expires_at")
    search_fields = ("message", "team__name", "feature_flag__key")
    autocomplete_fields = ("team", "feature_flag")
    readonly_fields = ("id", "created_at", "created_by")
    ordering = ("-starts_at",)
    list_select_related = ("team", "feature_flag", "created_by")
    fieldsets = (
        (None, {"fields": ("id", "team", "message")}),
        ("Targeting", {"fields": ("feature_flag",)}),
        ("Schedule", {"fields": ("starts_at", "expires_at", "is_active")}),
        ("Audit", {"fields": ("created_by", "created_at")}),
    )

    def get_queryset(self, request: HttpRequest) -> Any:
        # Staff admin needs all rows regardless of team scope context.
        return AgentNotice.objects.unscoped().all()

    def save_model(self, request: HttpRequest, obj: AgentNotice, form: Any, change: bool) -> None:
        if not change and request.user.is_authenticated:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Message")
    def message_preview(self, notice: AgentNotice) -> str:
        return notice.message[:80] + ("…" if len(notice.message) > 80 else "")

    @admin.display(description="Project", ordering="team__name")
    def team_link(self, notice: AgentNotice) -> str | SafeString:
        if notice.team is None:
            return "All projects (broadcast)"
        url = reverse("admin:posthog_team_change", args=[notice.team_id])
        return format_html('<a href="{}">{}</a>', url, notice.team.name)
