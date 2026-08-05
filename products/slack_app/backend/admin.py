from django.contrib import admin

from .models import SlackChannel, SlackSettings, SlackThreadTaskMapping, SlackUserProfileCache


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
        "permission_modes",
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


@admin.register(SlackThreadTaskMapping)
class SlackThreadTaskMappingAdmin(admin.ModelAdmin):
    list_select_related = ("team", "integration", "task", "task_run")
    list_display = (
        "id",
        "team",
        "integration",
        "slack_workspace_id",
        "channel",
        "thread_ts",
        "task",
        "task_run",
        "created_at",
    )
    list_filter = (
        "slack_workspace_id",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "slack_workspace_id",
        "channel",
        "thread_ts",
        "mentioning_slack_user_id",
        "task__title",
        "team__name",
        "team__organization__name",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("team", "integration", "task", "task_run")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("id", "team", "integration")}),
        (
            "Slack thread",
            {"fields": ("slack_workspace_id", "channel", "thread_ts", "mentioning_slack_user_id")},
        ),
        ("Task", {"fields": ("task", "task_run")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(SlackChannel)
class SlackChannelAdmin(admin.ModelAdmin):
    list_select_related = ("approved_by",)
    list_display = (
        "id",
        "slack_workspace_id",
        "slack_channel_id",
        "approved_at",
        "approved_by",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "slack_workspace_id",
        ("approved_at", admin.DateFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "slack_workspace_id",
        "slack_channel_id",
        "approved_by__email",
    )
    autocomplete_fields = ("approved_by",)
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-updated_at",)

    fieldsets = (
        (None, {"fields": ("id", "slack_workspace_id", "slack_channel_id")}),
        ("Approval", {"fields": ("approved_at", "approved_by")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(SlackUserProfileCache)
class SlackUserProfileCacheAdmin(admin.ModelAdmin):
    list_select_related = ("integration",)
    list_display = (
        "id",
        "integration",
        "slack_user_id",
        "email",
        "display_name",
        "real_name",
        "is_admin",
        "is_owner",
        "refreshed_at",
        "updated_at",
    )
    list_filter = (
        "is_admin",
        "is_owner",
        ("refreshed_at", admin.DateFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    search_fields = ("slack_user_id", "email", "display_name", "real_name")
    readonly_fields = ("id", "created_at", "updated_at", "refreshed_at")
    autocomplete_fields = ("integration",)
    ordering = ("-refreshed_at",)

    fieldsets = (
        (None, {"fields": ("id", "integration", "slack_user_id")}),
        ("Profile", {"fields": ("email", "display_name", "real_name", "is_admin", "is_owner")}),
        ("Dates", {"fields": ("created_at", "updated_at", "refreshed_at")}),
    )
