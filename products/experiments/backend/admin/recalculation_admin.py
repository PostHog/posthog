from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from products.experiments.backend.admin.recalculation_panel import (
    start_recalculation_for_experiment,
    temporal_workflow_url,
)
from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation
from products.experiments.backend.recalculation import cancel_recalculation_workflow

_TERMINAL_STATUSES = {
    ExperimentMetricsRecalculation.Status.COMPLETED,
    ExperimentMetricsRecalculation.Status.FAILED,
}


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
    # Operators drive state through the action buttons below, not field-by-field edits, so every field is
    # read-only. This is a pure admin-layer setting — no model or migration change.
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
    )
    # First page shows the latest 10; older runs stay reachable via pagination.
    list_per_page = 10
    change_form_template = "admin/experiments/experimentmetricsrecalculation/change_form.html"

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

    def has_add_permission(self, request) -> bool:
        # New runs are created through the "Start new recalculation" button (which also dispatches the
        # workflow), never via the bare admin add form that would leave an orphaned pending row.
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj is not None:
            # Hide the action buttons from a view-only staff user; the endpoints reject them too.
            can_manage = self.has_change_permission(request, obj)
            is_terminal = obj.status in _TERMINAL_STATUSES
            extra_context["can_mark_terminal"] = can_manage and not is_terminal
            extra_context["can_start_recalculation"] = can_manage
            extra_context["mark_failed_url"] = reverse("admin:experiments_recalculation_mark_failed", args=[obj.pk])
            extra_context["mark_completed_url"] = reverse(
                "admin:experiments_recalculation_mark_completed", args=[obj.pk]
            )
            extra_context["start_recalculation_url"] = reverse("admin:experiments_recalculation_start", args=[obj.pk])
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/mark-failed/",
                self.admin_site.admin_view(self.mark_failed_view),
                name="experiments_recalculation_mark_failed",
            ),
            path(
                "<path:object_id>/mark-completed/",
                self.admin_site.admin_view(self.mark_completed_view),
                name="experiments_recalculation_mark_completed",
            ),
            path(
                "<path:object_id>/start/",
                self.admin_site.admin_view(self.start_recalculation_view),
                name="experiments_recalculation_start",
            ),
            path(
                "<path:object_id>/retry-failures/",
                self.admin_site.admin_view(self.retry_failures_view),
                name="experiments_recalculation_retry_failures",
            ),
        ]
        return custom + urls

    def _mark_terminal(self, request, object_id, status: str):
        obj = self.get_object(request, object_id)
        if obj is None:
            return HttpResponseRedirect(reverse("admin:experiments_experimentmetricsrecalculation_changelist"))

        # admin_view only enforces is_staff; a view-only staff user must not be able to mutate the row.
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        change_url = reverse("admin:experiments_experimentmetricsrecalculation_change", args=[obj.pk])
        if request.method != "POST":
            return HttpResponseRedirect(change_url)

        # First-write-wins guard: only stamp a terminal status on a run that hasn't already finalized, so this
        # never clobbers a run the workflow completed a moment earlier. Mirrors the activity's completed_at guard.
        # for_team scopes the fail-closed write to the row's own team (admin runs outside request/team scope).
        updated = (
            ExperimentMetricsRecalculation.objects.for_team(obj.team_id)
            .filter(id=obj.pk, completed_at__isnull=True)
            .update(status=status, completed_at=timezone.now())
        )
        if not updated:
            messages.error(request, "This recalculation is already terminal; nothing to change.")
            return HttpResponseRedirect(change_url)

        cancel_recalculation_workflow(str(obj.pk))

        obj.refresh_from_db()
        self.log_change(request, obj, f"Manually marked {status} from admin.")
        messages.success(request, f"Recalculation marked {status}.")
        return HttpResponseRedirect(change_url)

    def mark_failed_view(self, request, object_id):
        return self._mark_terminal(request, object_id, ExperimentMetricsRecalculation.Status.FAILED)

    def mark_completed_view(self, request, object_id):
        return self._mark_terminal(request, object_id, ExperimentMetricsRecalculation.Status.COMPLETED)

    def start_recalculation_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            return HttpResponseRedirect(reverse("admin:experiments_experimentmetricsrecalculation_changelist"))
        change_url = reverse("admin:experiments_experimentmetricsrecalculation_change", args=[obj.pk])
        # A full recalculation of every metric: advances the window to now.
        return self._dispatch_recalculation(
            request, obj, change_url, trigger=ExperimentMetricsRecalculation.Trigger.MANUAL
        )

    def retry_failures_view(self, request: HttpRequest, object_id: str) -> HttpResponseRedirect:
        obj = self.get_object(request, object_id)
        if obj is None:
            return HttpResponseRedirect(reverse("admin:experiments_experimentmetricsrecalculation_changelist"))
        change_url = reverse("admin:experiments_experimentmetricsrecalculation_change", args=[obj.pk])
        # A metric-scoped change reuses the latest terminal run's window, so metrics that already succeeded
        # hit the (experiment, metric, query_to, fingerprint) cache and only the failed ones recompute.
        return self._dispatch_recalculation(
            request, obj, change_url, trigger=ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE
        )

    def _dispatch_recalculation(
        self, request: HttpRequest, obj: ExperimentMetricsRecalculation, change_url: str, *, trigger: str
    ) -> HttpResponseRedirect:
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        if request.method != "POST":
            return HttpResponseRedirect(change_url)

        return start_recalculation_for_experiment(request, obj.experiment, trigger=trigger, fallback_url=change_url)
