from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation
from products.experiments.backend.staff_operations import temporal_workflow_url


@admin.register(ExperimentMetricsRecalculation)
class ExperimentMetricsRecalculationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "experiment_link",
        "team_id",
        "status",
        "trigger",
        "total_metrics",
        "created_at",
        "started_at",
        "completed_at",
        "temporal_link",
    )
    list_filter = ("status", "trigger")
    search_fields = ("id", "experiment__id", "team__id")
    ordering = ("-created_at",)
    # Operators drive state through the PostHog Admin recalculations tool, not field-by-field edits, so every
    # field is read-only. This is a pure admin-layer setting — no model or migration change.
    readonly_fields = (
        "id",
        "team",
        "experiment",
        "status",
        "trigger",
        "total_metrics",
        "metric_uuids",
        "metric_errors",
        "metric_retries",
        "query_to",
        "created_at",
        "started_at",
        "completed_at",
        "created_by",
        "temporal_link",
        "console_link",
    )
    # First page shows the latest 10; older runs stay reachable via pagination.
    list_per_page = 10

    def get_queryset(self, request: HttpRequest) -> QuerySet[ExperimentMetricsRecalculation]:
        # `objects` is the fail-closed TeamScopedManager, which raises TeamScopeError without an ambient team
        # scope — and admin runs outside request/team scope, so the default manager would 500 every changelist
        # and detail render (and get_object, which reads through here). This admin is staff-only and manages
        # runs across all teams, so read cross-team through `unscoped()`, the prescribed escape hatch.
        return ExperimentMetricsRecalculation.objects.unscoped()

    @admin.display(description="Experiment")
    def experiment_link(self, obj: ExperimentMetricsRecalculation) -> str:
        url = reverse("admin:experiments_experiment_change", args=[obj.experiment_id])
        return format_html('<a href="{}">{}</a>', url, obj.experiment_id)

    @admin.display(description="Temporal workflow")
    def temporal_link(self, obj: ExperimentMetricsRecalculation) -> str:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">open in Temporal</a>', temporal_workflow_url(str(obj.id))
        )

    @admin.display(description="PostHog Admin")
    def console_link(self, obj: ExperimentMetricsRecalculation) -> str:
        return format_html(
            '<a href="{}?run={}">Mark failed or completed, start a new run: now in PostHog Admin &#8599;</a>',
            reverse("admin_console_tool", kwargs={"tool_key": "experiment-recalculations"}),
            obj.pk,
        )

    def has_add_permission(self, request) -> bool:
        # New runs are created through "Start new recalculation" in PostHog Admin (which also dispatches the
        # workflow), never via the bare admin add form that would leave an orphaned pending row.
        return False
