from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from products.experiments.backend.models.experiment import ExperimentSavedMetric


@admin.register(ExperimentSavedMetric)
class ExperimentSavedMetricAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "engine",
        "migrated_links",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)
    readonly_fields = ("console_link",)

    @admin.display(description="Team")
    def team_link(self, saved_metric: ExperimentSavedMetric):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[saved_metric.team.pk]),
            saved_metric.team.name,
        )

    @admin.display(description="Engine")
    def engine(self, saved_metric: ExperimentSavedMetric):
        kind = saved_metric.query.get("kind") if saved_metric.query else None
        if kind in ("ExperimentFunnelsQuery", "ExperimentTrendsQuery"):
            return mark_safe('<span style="color: orange;">Legacy</span>')
        return ""

    @admin.display(description="")
    def migrated_links(self, saved_metric: ExperimentSavedMetric):
        if saved_metric.metadata and "migrated_from" in saved_metric.metadata:
            return format_html(
                '<a href="{}">Migrated From: {}</a>',
                reverse(
                    "admin:experiments_experimentsavedmetric_change", args=[saved_metric.metadata["migrated_from"]]
                ),
                saved_metric.metadata["migrated_from"],
            )
        if saved_metric.metadata and "migrated_to" in saved_metric.metadata:
            return format_html(
                '<a href="{}">Migrated To: {}</a>',
                reverse("admin:experiments_experimentsavedmetric_change", args=[saved_metric.metadata["migrated_to"]]),
                saved_metric.metadata["migrated_to"],
            )
        return ""

    @admin.display(description="PostHog Admin")
    def console_link(self, saved_metric: ExperimentSavedMetric):
        return format_html(
            '<a href="{}?saved_metric={}">Legacy engine migration: now in PostHog Admin &#8599;</a>',
            reverse("admin_console_tool", kwargs={"tool_key": "experiments"}),
            saved_metric.pk,
        )
