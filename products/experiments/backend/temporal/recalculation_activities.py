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
) -> MetricRecalculationResult:
    """Calculate one metric, write its recalc-fingerprinted result to ExperimentMetricResult, and fold the
    progress update (counter + error) into the same job atomically. query_to is the run's shared data-window end.

    metric_type is the primary/secondary classification carried from discovery; it's threaded into the per-metric
    PostHog event so the capture path doesn't have to re-query the saved-metric M2M to resolve it. Defaults to
    "primary" so existing call sites and tests that don't pass it remain valid.
    """
    return await _calculate_experiment_metric_for_recalculation_sync(
        experiment_id, metric_uuid, recalculation_id, query_to, metric_type
    )


@temporalio.activity.defn
async def resolve_single_metric_retry_context(recalculation_id: str, metric_uuid: str) -> dict:
    """Resolve experiment_id / query_to / metric_type for a single-metric retry from the run row.

    Runs before the calc activity in the retry workflow, since the workflow can't read the DB directly.
    """
    # Deferred import to break a load-time cycle: recalculation.py imports recalculation_logic.py, and the
    # worker registry imports this activities module, so importing recalculation.py at top would partially
    # initialize it during codegen/startup. noqa: PLC0415 — justified circular-import break.
    from products.experiments.backend.recalculation import resolve_single_metric_retry_context as _impl  # noqa: PLC0415

    return await _impl(recalculation_id, metric_uuid)


@temporalio.activity.defn
async def finalize_single_metric_retry(recalculation_id: str, metric_uuid: str) -> None:
    """Reconcile the run row after a single-metric retry: clear the metric's error on success, recompute status."""
    # Deferred import to break a load-time cycle (see resolve_single_metric_retry_context above).
    from products.experiments.backend.recalculation import finalize_single_metric_retry as _impl  # noqa: PLC0415

    return await _impl(recalculation_id, metric_uuid)
