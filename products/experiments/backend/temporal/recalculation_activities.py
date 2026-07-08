"""Temporal activity entrypoints for experiment metrics recalculation.

These are thin ``@temporalio.activity.defn`` wrappers; the DB-touching implementations and helpers live in
``recalculation_logic``. Keeping the decorated entrypoints isolated makes the worker-registered surface obvious
and lets the logic be unit-tested without the activity decorator.
"""

import temporalio.activity

from products.experiments.backend.temporal.models import (
    ExperimentMetricToRecalculate,
    MetricRecalculationResult,
    RecalculationProgressUpdate,
)
from products.experiments.backend.temporal.recalculation_logic import (
    _calculate_experiment_metric_for_recalculation_sync,
    _discover_experiment_metrics_sync,
    _update_recalculation_progress_sync,
)


@temporalio.activity.defn
async def discover_experiment_metrics(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
    """Discover all metrics (inline + saved/shared) for an experiment and persist their uuids onto the job."""
    return await _discover_experiment_metrics_sync(recalculation_id)


@temporalio.activity.defn
async def update_recalculation_progress(update: RecalculationProgressUpdate) -> str | None:
    """Update job progress. Used only for the start (in_progress + total + query_to) and finish (final status) steps.

    Returns the run's shared query_to as an ISO string when starting (mark_started); otherwise None.
    """
    return await _update_recalculation_progress_sync(update)


@temporalio.activity.defn
async def calculate_experiment_metric_for_recalculation(
    experiment_id: int,
    metric_uuid: str,
    recalculation_id: str,
    query_to: str,
    metric_type: str = "primary",
    is_final_attempt: bool = True,
) -> MetricRecalculationResult:
    """Calculate one metric, write its recalc-fingerprinted result to ExperimentMetricResult, and fold the
    progress update (counter + error) into the same job atomically. query_to is the run's shared data-window end.

    metric_type is the primary/secondary classification carried from discovery; it's threaded into the per-metric
    PostHog event so the capture path doesn't have to re-query the saved-metric M2M to resolve it. Defaults to
    "primary" so existing call sites and tests that don't pass it remain valid.

    is_final_attempt is owned by the workflow's requeue loop (the activity runs with maximum_attempts=1, so it
    can't infer this from activity.info().attempt). On the final attempt a transient failure is persisted rather
    than re-raised silently, so the row reflects the real outcome once the workflow stops retrying. Defaults to
    True so callers that don't pass it persist failures eagerly.
    """
    return await _calculate_experiment_metric_for_recalculation_sync(
        experiment_id, metric_uuid, recalculation_id, query_to, metric_type, is_final_attempt
    )
