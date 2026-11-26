from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import (
    SlackChannel,
    SlackDailyFocus,
    SlackSettings,
    SlackThreadJoin,
    SlackThreadTaskMapping,
    SlackUserProfileCache,
)
from .services.slack_settings import onboarding_status_label, reset_onboarding


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
        "channel_welcome_mode",
        "onboarding_status",
        "updated_at",
    )
    list_filter = ("slack_workspace_id", "created_at")
    actions = ("reset_onboarding",)
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

    @admin.display(description="Onboarding")
    def onboarding_status(self, obj: SlackSettings) -> str:
        return onboarding_status_label(obj.onboarding)

    @admin.action(description="Reset onboarding (a new thread on the next trigger)")
    def reset_onboarding(self, request: HttpRequest, queryset: QuerySet[SlackSettings]) -> None:
        count = reset_onboarding(list(queryset.values_list("id", flat=True)))
        self.message_user(request, f"Reset the onboarding of {count} {'person' if count == 1 else 'people'}.")


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


@admin.register(SlackThreadJoin)
class SlackThreadJoinAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "thread_mapping", "slack_user_id", "created_at")
    list_filter = (("created_at", admin.DateFieldListFilter),)
    search_fields = (
        "slack_user_id",
        "thread_mapping__slack_workspace_id",
        "thread_mapping__channel",
        "thread_mapping__thread_ts",
        "team__name",
    )
    readonly_fields = ("id", "created_at")
    autocomplete_fields = ("team", "thread_mapping")
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[SlackThreadJoin]:
        # Admin has no team context; SlackThreadJoin's default manager is fail-closed.
        return SlackThreadJoin.objects.unscoped().select_related("team", "thread_mapping")


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


class SlackDailyFocusStateFilter(admin.SimpleListFilter):
    title = "daily work focus"
    parameter_name = "state"

    # nosemgrep: tuple-return-prefer-dataclass -- Django requires (value, label) lookup pairs.
    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        return [("on", "On"), ("off", "Off")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[SlackDailyFocus]) -> QuerySet[SlackDailyFocus]:
        if self.value() == "on":
            return queryset.filter(next_run_at__isnull=False)
        if self.value() == "off":
            return queryset.filter(next_run_at__isnull=True)
        return queryset


@admin.register(SlackDailyFocus)
class SlackDailyFocusAdmin(admin.ModelAdmin):
    """Read only: changing the time here would not move the next run, and a deleted row reads as "never chose", so
    the default would turn the daily work focus back on for a person who turned it off."""

    list_display = (
        "id",
        "slack_workspace_id",
        "slack_user_id",
        "team",
        "state",
        "at",
        "next_run_at",
        "last_run_at",
        "sent_at",
        "updated_at",
    )
    list_filter = (SlackDailyFocusStateFilter, "slack_workspace_id", ("last_run_at", admin.DateFieldListFilter))
    search_fields = ("slack_workspace_id", "slack_user_id", "team__name", "team__organization__name")
    ordering = ("-updated_at",)

    fieldsets = (
        (None, {"fields": ("id", "team", "integration_id", "slack_workspace_id", "slack_user_id")}),
        ("Schedule", {"fields": ("at", "next_run_at", "last_run_at", "sent_at")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[SlackDailyFocus]:
        # Admin has no team context; SlackDailyFocus's default manager is fail-closed.
        return SlackDailyFocus.objects.unscoped().select_related("team")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: SlackDailyFocus | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: SlackDailyFocus | None = None) -> bool:
        return False

    @admin.display(description="State")
    def state(self, obj: SlackDailyFocus) -> str:
        return "On" if obj.next_run_at else "Off"
