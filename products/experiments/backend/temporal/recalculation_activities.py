from datetime import UTC, datetime
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

import structlog
import temporalio.activity

from posthog.sync import database_sync_to_async

from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation
from products.experiments.backend.temporal.models import ExperimentMetricToRecalculate, RecalculationProgressUpdate

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _discover_experiment_metrics_sync(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
    close_old_connections()

    recalculation = ExperimentMetricsRecalculation.objects.select_related("experiment").get(id=recalculation_id)
    experiment = recalculation.experiment

    metrics_to_recalculate: list[ExperimentMetricToRecalculate] = []

    def _add(metric_uuid: str | None, metric_type: str) -> None:
        if metric_uuid:
            metrics_to_recalculate.append(
                ExperimentMetricToRecalculate(
                    experiment_id=experiment.id, metric_uuid=metric_uuid, metric_type=metric_type
                )
            )

    # Inline metrics carry their uuid directly on the dict; the metric_type is the source list.
    for source, metric_type in [(experiment.metrics, "primary"), (experiment.metrics_secondary, "secondary")]:
        for metric in source or []:
            _add(metric.get("uuid"), metric_type)

    # Saved (shared) metrics live in the M2M through-model: uuid is on saved_metric.query["uuid"], and
    # primary/secondary is recorded on the link's metadata["type"] (default "primary").
    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        saved_query = link.saved_metric.query
        metric_uuid = saved_query.get("uuid") if saved_query else None
        metric_type = link.metadata.get("type", "primary") if link.metadata else "primary"
        _add(metric_uuid, metric_type)

    recalculation.metric_uuids = [m.metric_uuid for m in metrics_to_recalculate]
    recalculation.save(update_fields=["metric_uuids"])

    logger.info(
        "Discovered experiment metrics for recalculation",
        recalculation_id=recalculation_id,
        count=len(metrics_to_recalculate),
    )
    return metrics_to_recalculate


@temporalio.activity.defn
async def discover_experiment_metrics(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
    """Discover all metrics (inline + saved/shared) for an experiment and persist their uuids onto the job."""
    return await _discover_experiment_metrics_sync(recalculation_id)


@database_sync_to_async
def _update_recalculation_progress_sync(update: RecalculationProgressUpdate) -> str | None:
    close_old_connections()

    updates: dict[str, Any] = {}
    if update.status:
        updates["status"] = update.status
    if update.total_metrics is not None:
        updates["total_metrics"] = update.total_metrics
    if update.metric_uuids is not None:
        updates["metric_uuids"] = update.metric_uuids
    if update.mark_completed:
        updates["completed_at"] = timezone.now()

    query_to: datetime | None = None
    if update.mark_started:
        # Set the single data-window end once, when the run starts. All metrics (and retries) use this value.
        query_to = datetime.now(UTC)
        updates["started_at"] = timezone.now()
        updates["query_to"] = query_to

    if updates:
        ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id).update(**updates)

    # Option A: return the query_to the start step set, so the workflow can thread it into every calc activity.
    return query_to.isoformat() if query_to is not None else None


@temporalio.activity.defn
async def update_recalculation_progress(update: RecalculationProgressUpdate) -> str | None:
    """Update job progress. Used only for the start (in_progress + total + query_to) and finish (final status) steps.

    Returns the run's shared query_to as an ISO string when starting (mark_started); otherwise None.
    """
    return await _update_recalculation_progress_sync(update)
