from django.contrib import admin

from .models import SlackSettings


@admin.register(SlackSettings)
class SlackSettingsAdmin(admin.ModelAdmin):
    list_select_related = (
        "default_integration",
        "default_integration__team",
        "default_integration__team__organization",
    )
    list_display = (
        "id",
        "slack_workspace_id",
        "slack_user_id",
        "default_integration",
        "updated_at",
    )
    list_filter = ("slack_workspace_id", "created_at")
    search_fields = (
        "slack_workspace_id",
        "slack_user_id",
        "default_integration__integration_id",
        "default_integration__team__name",
        "default_integration__team__organization__name",
    )
    autocomplete_fields = ("default_integration",)
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-updated_at",)
