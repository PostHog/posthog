"""Product analytics events for the recalculation flow."""

from typing import Any

import structlog
import posthoganalytics

from posthog.event_usage import groups

from products.experiments.backend.metric_resolution import get_metrics_for_calculation
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.temporal.models import RecalculationProgressUpdate

logger = structlog.get_logger(__name__)


def _capture_results_refresh_completed(update: RecalculationProgressUpdate) -> None:
    """Run-level analytics: 'experiment results refresh completed' with the final counts. Mirrors the
    legacy client-side event. Telemetry must never fail the activity, so swallow any error."""
    try:
        recalc = (
            ExperimentMetricsRecalculation.objects.select_related("experiment", "experiment__team")
            .filter(id=update.recalculation_id)
            .first()
        )
        if recalc is None:
            return
        experiment = recalc.experiment
        team = experiment.team
        distinct_id = (
            experiment.created_by.distinct_id
            if experiment.created_by and experiment.created_by.distinct_id
            else f"team_{team.id}"
        )
        total_duration_ms = (
            round((recalc.completed_at - recalc.created_at).total_seconds() * 1000)
            if recalc.completed_at and recalc.created_at
            else None
        )
        # Split the full duration into the time the workflow actually executed (start activity to finish)
        # and the time it waited in the queue before the start activity ran (request to start). Their sum
        # is total_duration_ms. started_at is set by the start activity, so it is present on any completed run.
        execution_duration_ms = (
            round((recalc.completed_at - recalc.started_at).total_seconds() * 1000)
            if recalc.completed_at and recalc.started_at
            else None
        )
        queue_duration_ms = (
            round((recalc.started_at - recalc.created_at).total_seconds() * 1000)
            if recalc.started_at and recalc.created_at
            else None
        )
        # Hours since the start date, matching the legacy frontend definition exactly
        # (now - start_date, ignoring end_date) so dashboards can share the >12h filter across paths.
        hours_since_start = experiment.hours_since_start
        experiment_duration_hours = round(hours_since_start) if hours_since_start is not None else None
        # Count from the discovery list that also sets total_metrics, so saved metrics count and legacy
        # metrics that the run never calculates do not.
        roles = [metric.role for metric in get_metrics_for_calculation(experiment)]
        primary_metrics_count = roles.count("primary")
        secondary_metrics_count = roles.count("secondary")
        # Global client, like most Temporal workflows: the worker is long-lived, so its background flush
        # runs fine, and a scoped client's synchronous shutdown stalls the activity (~2x flush_interval).
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event="experiment results refresh completed",
            properties={
                **(
                    {"$update_person_last_seen_at": False}
                    if recalc.trigger == ExperimentMetricsRecalculation.Trigger.SCHEDULED
                    else {}
                ),
                "experiment_id": experiment.id,
                "team_id": team.id,
                "recalculation_id": str(recalc.id),
                "status": recalc.status,
                "total_metrics": recalc.total_metrics,
                "succeeded_metrics": update.succeeded_metrics,
                "failed_metrics": update.failed_metrics,
                "total_duration_ms": total_duration_ms,
                "execution_duration_ms": execution_duration_ms,
                "queue_duration_ms": queue_duration_ms,
                "trigger": recalc.trigger,
                "execution_mode": "recalculation",
                # Legacy-named aliases + missing properties for parity with the frontend
                # 'experiment results refresh completed' event, so the original experiments
                # dashboards work against workflow runs with the same property names.
                "triggered_by": recalc.trigger,
                "successful_count": update.succeeded_metrics,
                "errored_count": update.failed_metrics,
                "cached_count": 0,
                "total_metrics_count": recalc.total_metrics,
                "primary_metrics_count": primary_metrics_count,
                "secondary_metrics_count": secondary_metrics_count,
                "experiment_status": experiment.status or experiment.computed_status,
                "experiment_duration_hours": experiment_duration_hours,
            },
            groups=groups(organization=team.organization, team=team),
        )
    except Exception:
        logger.warning(
            "experiment_results_refresh_completed_capture_failed",
            recalculation_id=update.recalculation_id,
            exc_info=True,
        )


# These mirror the legacy client-side events ('experiment metric finished' / 'experiment metric error'),
# now that metrics are computed on the backend instead of in the browser. execution_mode='recalculation'
# distinguishes them from legacy events on the same dashboards.
def _capture_experiment_metric_event(
    experiment: Experiment,
    metric_uuid: str,
    role: str,
    metric_dict: dict | None,
    event: str,
    extra_properties: dict[str, Any],
    trigger: str | None = None,
) -> None:
    """Emit a per-metric product analytics event. Telemetry must never fail the activity, so any error
    is swallowed. Attributed to the experiment creator, falling back to a team-scoped distinct_id.

    `role` ("primary" or "secondary") is carried from discovery in `ExperimentMetricToRecalculate.role`,
    threaded through the workflow + activity args so the capture path doesn't have to re-query the M2M to
    resolve it.

    """
    try:
        team = experiment.team
        distinct_id = (
            experiment.created_by.distinct_id
            if experiment.created_by and experiment.created_by.distinct_id
            else f"team_{team.id}"
        )
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event,
            properties={
                "experiment_id": experiment.id,
                "team_id": team.id,
                "metric_uuid": metric_uuid,
                **(
                    {"$update_person_last_seen_at": False}
                    if trigger == ExperimentMetricsRecalculation.Trigger.SCHEDULED
                    else {}
                ),
                "metric_kind": (metric_dict or {}).get("metric_type"),
                "is_primary": role == "primary",
                "execution_mode": "recalculation",
                "context": "ui",
                "mechanism": "orchestrated",
                "trigger": trigger,
                **extra_properties,
            },
            groups=groups(organization=team.organization, team=team),
        )
    except Exception:
        logger.warning(
            "experiment_metric_event_capture_failed",
            event=event,
            experiment_id=experiment.id,
            metric_uuid=metric_uuid,
            exc_info=True,
        )
