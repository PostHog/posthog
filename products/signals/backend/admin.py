import re

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from products.skills.backend.models.skills import LLMSkill

from .models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
    SignalScratchpad,
    SignalTeamConfig,
)
from .scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX


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
        "run_cron_schedule",
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


class SignalScoutNoteAdminForm(forms.ModelForm):
    class Meta:
        model = SignalScoutNote
        fields = "__all__"

    def clean(self) -> dict:
        # Mirror the API write path (`scout_harness/tools/notes.py`): the run-time list matches
        # `skill_name` exactly, so a typo'd target saved here would silently steer no one.
        cleaned = super().clean() or {}
        skill_name = (cleaned.get("skill_name") or "").strip()
        cleaned["skill_name"] = skill_name
        if not skill_name:
            return cleaned
        if not skill_name.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
            raise forms.ValidationError(
                {"skill_name": f"Must be blank (a note for every scout) or start with '{SIGNALS_SCOUT_SKILL_PREFIX}'."}
            )
        team = cleaned.get("team")
        if team is not None and not LLMSkill.objects.filter(team=team, name=skill_name, deleted=False).exists():
            raise forms.ValidationError({"skill_name": "No scout skill with this name exists on the selected team."})
        return cleaned


@admin.register(SignalScoutNote)
class SignalScoutNoteAdmin(admin.ModelAdmin):
    form = SignalScoutNoteAdminForm
    list_display = ("id", "team_link", "skill_name", "created_by", "expires_at", "created_at")
    list_display_links = ("id",)
    search_fields = ("id", "team__name", "team__organization__name", "skill_name", "content")
    raw_id_fields = ("team", "created_by")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at")
    list_select_related = ("team", "team__organization", "created_by")
    show_full_result_count = False

    @admin.display(description="Team")
    def team_link(self, note: SignalScoutNote):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[note.team.pk]),
            note.team.name,
        )


# Slack channel ids are uppercase alphanumerics starting with C/G/D (public/private/DM). The notifier
# keys off the id (the part before "|"), so a display name or "#name" saved here silently drops every
# team-default notification — reject those shapes before they reach the DB.
_SLACK_CHANNEL_ID_RE = re.compile(r"^[CGD][A-Z0-9]{6,}$")


class SignalTeamConfigAdminForm(forms.ModelForm):
    class Meta:
        model = SignalTeamConfig
        fields = "__all__"

    def clean_default_slack_notification_channel(self) -> str | None:
        value = (self.cleaned_data.get("default_slack_notification_channel") or "").strip()
        if not value:
            return None
        # Only the channel id is required; an optional "|#name" suffix is allowed for readability.
        channel_id = value.split("|", 1)[0].strip()
        if not _SLACK_CHANNEL_ID_RE.match(channel_id):
            raise forms.ValidationError(
                "Use 'CHANNELID|#name' form, or just the channel id. The id looks like 'C0123ABCD' "
                "(copy it from the channel's details in Slack) — a '#name' won't work."
            )
        return value


@admin.register(SignalTeamConfig)
class SignalTeamConfigAdmin(admin.ModelAdmin):
    form = SignalTeamConfigAdminForm
    list_display = (
        "id",
        "team_link",
        "autostart_enabled",
        "default_autostart_priority",
        "default_slack_notification_channel",
        "updated_at",
    )
    list_display_links = ("id",)
    search_fields = ("id", "team__name", "team__organization__name", "default_slack_notification_channel")
    raw_id_fields = ("team",)
    # autostart_base_branches is free-form JSON with no form-level shape check; a non-dict value would
    # crash the autostart worker (it calls .get() on it). It's owned by the API, so keep it read-only here.
    readonly_fields = ("id", "autostart_base_branches", "created_at", "updated_at")
    list_select_related = ("team", "team__organization")
    show_full_result_count = False

    @admin.display(description="Team")
    def team_link(self, config: SignalTeamConfig):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[config.team.pk]),
            config.team.name,
        )
