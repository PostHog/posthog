from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutRun,
    SignalScratchpad,
    SignalTeamConfig,
)


class SignalReportArtefactInline(admin.TabularInline):
    model = SignalReportArtefact
    extra = 0
    fields = ("id", "type", "content_preview", "created_at")
    readonly_fields = fields
    can_delete = False

    @admin.display(description="Content preview")
    def content_preview(self, obj: SignalReportArtefact) -> str:
        return (obj.content[:200] + "...") if len(obj.content) > 200 else obj.content


@admin.register(SignalReport)
class SignalReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_link",
        "status",
        "title",
        "signal_count",
        "total_weight",
        "created_at",
        "promoted_at",
    )
    list_display_links = ("id",)
    list_filter = ("status",)
    search_fields = ("id", "team__name", "team__organization__name", "title", "summary")
    ordering = ("-created_at",)
    show_full_result_count = False
    list_select_related = ("team", "team__organization")

    @admin.display(description="Team")
    def team_link(self, report: SignalReport):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[report.team.pk]),
            report.team.name,
        )

    readonly_fields = (
        "id",
        "team",
        "status",
        "total_weight",
        "signal_count",
        "signals_at_run",
        "title",
        "summary",
        "error",
        "created_at",
        "updated_at",
        "promoted_at",
        "last_run_at",
    )

    fieldsets = (
        (None, {"fields": ("id", "team", "status")}),
        ("Content", {"fields": ("title", "summary", "error")}),
        ("Stats", {"fields": ("signal_count", "total_weight", "signals_at_run")}),
        ("Dates", {"fields": ("created_at", "updated_at", "promoted_at", "last_run_at")}),
    )

    inlines = [SignalReportArtefactInline]


@admin.register(SignalScoutConfig)
class SignalScoutConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_link",
        "skill_name",
        "enabled",
        "emit",
        "run_interval_minutes",
        "last_run_at",
        "updated_at",
    )
    list_display_links = ("id",)
    list_filter = ("enabled", "emit")
    search_fields = ("id", "skill_name", "team__name", "team__organization__name")
    raw_id_fields = ("team", "created_by", "enabled_by")
    readonly_fields = ("id", "created_at", "updated_at", "last_run_at")
    list_select_related = ("team", "team__organization")
    show_full_result_count = False

    @admin.display(description="Team")
    def team_link(self, config: SignalScoutConfig):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[config.team.pk]),
            config.team.name,
        )


@admin.register(SignalScoutRun)
class SignalScoutRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_link",
        "skill_name",
        "skill_version",
        "created_at",
    )
    list_display_links = ("id",)
    list_filter = ("skill_name",)
    search_fields = ("id", "team__name", "team__organization__name", "skill_name")
    raw_id_fields = ("team", "scout_config", "task_run")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "team",
        "scout_config",
        "task_run",
        "skill_name",
        "skill_version",
        "created_at",
    )
    list_select_related = ("team", "team__organization", "scout_config", "task_run")
    show_full_result_count = False

    @admin.display(description="Team")
    def team_link(self, run: SignalScoutRun):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[run.team.pk]),
            run.team.name,
        )


@admin.register(SignalScratchpad)
class SignalScratchpadAdmin(admin.ModelAdmin):
    list_display = ("id", "team_link", "key", "created_at")
    list_display_links = ("id",)
    search_fields = ("id", "team__name", "team__organization__name", "key", "content")
    raw_id_fields = ("team", "created_by_run")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at")
    list_select_related = ("team", "team__organization")
    show_full_result_count = False

    @admin.display(description="Team")
    def team_link(self, scratchpad: SignalScratchpad):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[scratchpad.team.pk]),
            scratchpad.team.name,
        )


@admin.register(SignalTeamConfig)
class SignalTeamConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_link",
        "default_autostart_priority",
        "default_slack_notification_channel",
        "updated_at",
    )
    list_display_links = ("id",)
    search_fields = ("id", "team__name", "team__organization__name", "default_slack_notification_channel")
    raw_id_fields = ("team",)
    readonly_fields = ("id", "created_at", "updated_at")
    list_select_related = ("team", "team__organization")
    show_full_result_count = False

    @admin.display(description="Team")
    def team_link(self, config: SignalTeamConfig):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[config.team.pk]),
            config.team.name,
        )
