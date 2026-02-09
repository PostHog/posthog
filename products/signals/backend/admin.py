from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import SignalReport, SignalReportArtefact


class SignalReportArtefactInline(admin.TabularInline):
    model = SignalReportArtefact
    extra = 0
    fields = ("id", "type", "content_size", "created_at")
    readonly_fields = fields
    can_delete = False

    @admin.display(description="Content size (bytes)")
    def content_size(self, obj: SignalReportArtefact) -> int:
        return len(obj.content) if obj.content else 0


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
        "conversation",
        "signals_at_run",
        "title",
        "summary",
        "error",
        "created_at",
        "updated_at",
        "promoted_at",
        "last_run_at",
        "relevant_user_count",
        "cluster_centroid_updated_at",
    )

    fieldsets = (
        (None, {"fields": ("id", "team", "status")}),
        ("Content", {"fields": ("title", "summary", "error")}),
        ("Stats", {"fields": ("signal_count", "total_weight", "relevant_user_count", "signals_at_run")}),
        ("Related", {"fields": ("conversation",)}),
        ("Clustering", {"fields": ("cluster_centroid_updated_at",)}),
        ("Dates", {"fields": ("created_at", "updated_at", "promoted_at", "last_run_at")}),
    )

    inlines = [SignalReportArtefactInline]
