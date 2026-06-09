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
    experiment_id: int, metric_uuid: str, recalculation_id: str, query_to: str
) -> MetricRecalculationResult:
    """Calculate one metric, write its recalc-fingerprinted result to ExperimentMetricResult, and fold the
    progress update (counter + error) into the same job atomically. query_to is the run's shared data-window end.
    """
    return await _calculate_experiment_metric_for_recalculation_sync(
        experiment_id, metric_uuid, recalculation_id, query_to
    )
