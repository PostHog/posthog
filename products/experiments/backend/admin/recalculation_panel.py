"""Shared read helpers for the admin "latest recalculation" panel.

Both the Experiment change page and the ExperimentMetricsRecalculation change page render the same
summary: run status, timing, and a table of per-metric failures with the message a user sees on the
experiment page. Keeping the shaping here means both admin classes stay thin and the failure-resolution
order stays in one place, matching the frontend resolver in experimentMetricsLogic.ts.
"""

from datetime import datetime
from typing import cast

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from posthog.models.user import User

from products.experiments.backend.metric_events import _default_metric_title
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import (
    _derive_counters,
    get_run_results,
    request_recalculation,
    start_metrics_recalculation_workflow,
)
from products.experiments.backend.temporal.metric_resolution import build_metric, find_metric_dict


def format_duration(started_at: datetime | None, completed_at: datetime | None) -> str | None:
    """Human-friendly run duration, e.g. "4m 10s" or "45s". None when either bound is missing."""
    if started_at is None or completed_at is None:
        return None
    total_seconds = int((completed_at - started_at).total_seconds())
    if total_seconds < 0:
        return None
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    # Always show seconds so a sub-minute run reads as "45s" rather than an empty string.
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _metric_name(experiment: Experiment, metric_uuid: str) -> str:
    """Resolve a metric_uuid to the title a user sees, falling back to the uuid for a metric that no
    longer resolves on the experiment (removed after the run)."""
    metric_dict = find_metric_dict(experiment, metric_uuid)
    if metric_dict is None:
        return metric_uuid
    if metric_dict.get("name"):
        return metric_dict["name"]
    try:
        return _default_metric_title(build_metric(metric_dict)) or metric_uuid
    except Exception:
        return metric_uuid


def _resolve_failures(recalc: ExperimentMetricsRecalculation, results: list[dict]) -> list[dict]:
    """Per-metric failures as {metric_uuid, metric_name, error}, matching the frontend resolver:
    metric_errors wins (it covers discovery-step failures absent from results), then a FAILED result
    row's error_message.
    """
    metric_errors = recalc.metric_errors or {}
    failed_row_message = {
        row["metric_uuid"]: row["error_message"]
        for row in results
        if row["status"] == ExperimentMetricResult.Status.FAILED and row["error_message"]
    }

    # Union of every uuid that failed either way, so a discovery-step failure with no result row still shows.
    failed_uuids = set(metric_errors.keys()) | set(failed_row_message.keys())
    failures = []
    for metric_uuid in failed_uuids:
        error = None
        entry = metric_errors.get(metric_uuid)
        if isinstance(entry, dict):
            error = entry.get("message")
        error = error or failed_row_message.get(metric_uuid)
        if not error:
            continue
        failures.append(
            {
                "metric_uuid": metric_uuid,
                "metric_name": _metric_name(recalc.experiment, metric_uuid),
                "error": error,
            }
        )
    failures.sort(key=lambda f: f["metric_name"].lower())
    return failures


def temporal_workflow_url(recalculation_id: str) -> str:
    """Link to the recalc's Temporal Cloud workflow. Uses the runtime namespace (e.g. posthog-prod-us.usz2o),
    so it resolves per region without hardcoding a slug."""
    return (
        f"https://cloud.temporal.io/namespaces/{settings.TEMPORAL_NAMESPACE}"
        f"/workflows/experiment-metrics-recalculation-{recalculation_id}"
    )


def build_recalculation_panel(recalc: ExperimentMetricsRecalculation) -> dict:
    """Shape one recalculation row for the admin panel: status, timing, human duration, failures table,
    and the links the template renders (all recalculations, Temporal workflow, retry)."""
    results = get_run_results(recalc)
    completed_metrics, failed_metrics = _derive_counters(recalc, results=results)
    failures = _resolve_failures(recalc, results)

    all_recalculations_url = (
        reverse("admin:experiments_experimentmetricsrecalculation_changelist")
        + f"?experiment__id__exact={recalc.experiment_id}"
    )

    return {
        "id": str(recalc.id),
        "status": recalc.get_status_display(),
        "trigger": recalc.get_trigger_display(),
        "total_metrics": recalc.total_metrics,
        "completed_metrics": completed_metrics,
        "failed_metrics": failed_metrics,
        "started_at": recalc.started_at,
        "completed_at": recalc.completed_at,
        "duration_human": format_duration(recalc.started_at, recalc.completed_at),
        "failures": failures,
        "has_failures": bool(failures),
        "all_recalculations_url": all_recalculations_url,
        "temporal_url": temporal_workflow_url(str(recalc.id)),
        "retry_url": reverse("admin:experiments_recalculation_retry_failures", args=[recalc.pk]),
    }


def start_recalculation_for_experiment(
    request: HttpRequest, experiment: Experiment, *, trigger: str, fallback_url: str
) -> HttpResponseRedirect:
    """Create a recalculation and dispatch its workflow, then redirect to the new run's change page.

    Shared by every admin action that starts a run (start new, retry failures). Mirrors the API's create +
    start path: an active run already existing returns is_existing and reuses it; a workflow that fails to
    start rolls the fresh row back to FAILED so it is never left pending forever.
    """
    try:
        # admin_view gates these callers to staff, so request.user is always a real User, not AnonymousUser.
        result = request_recalculation(experiment, cast(User, request.user), trigger=trigger)
    except Exception as e:
        messages.error(request, f"Could not create recalculation: {e}")
        return HttpResponseRedirect(fallback_url)

    if result.get("is_existing"):
        messages.info(request, "An active recalculation already exists for this experiment; reused it.")
        return HttpResponseRedirect(fallback_url)

    recalculation_id = str(result["id"])
    try:
        start_metrics_recalculation_workflow(recalculation_id, str(experiment.team.organization_id))
    except Exception as e:
        ExperimentMetricsRecalculation.objects.for_team(experiment.team_id).filter(id=recalculation_id).update(
            status=ExperimentMetricsRecalculation.Status.FAILED
        )
        messages.error(request, f"Created the row but failed to start the workflow (marked failed): {e}")
        return HttpResponseRedirect(fallback_url)

    new_change_url = reverse("admin:experiments_experimentmetricsrecalculation_change", args=[recalculation_id])
    messages.success(
        request, format_html('Started new recalculation <a href="{}">{}</a>.', new_change_url, recalculation_id)
    )
    return HttpResponseRedirect(new_change_url)
