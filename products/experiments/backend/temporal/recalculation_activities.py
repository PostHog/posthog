"""Temporal activity entrypoints for experiment metrics recalculation.

These are thin ``@temporalio.activity.defn`` wrappers; the DB-touching implementations and helpers live in
``recalculation_logic``. Keeping the decorated entrypoints isolated makes the worker-registered surface obvious
and lets the logic be unit-tested without the activity decorator.
"""

import asyncio

import structlog
import temporalio.activity

from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import on_asyncify_pool

from products.experiments.backend.temporal.models import (
    MAX_METRIC_ATTEMPTS,
    METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS,
    ExperimentMetricToRecalculate,
    MetricOutOfTimeFailure,
    MetricRecalculationResult,
    RecalculationProgressUpdate,
)
from products.experiments.backend.temporal.recalculation_logic import (
    _calculate_experiment_metric_for_recalculation_sync,
    _cancel_metric_query_sync,
    _discover_experiment_metrics_sync,
    _record_metric_out_of_time_failure_sync,
    _update_recalculation_progress_sync,
)

logger = structlog.get_logger(__name__)

_CANCEL_KILL_RETRY_INTERVAL_SECONDS = 2.0

# Heartbeat every heartbeat_timeout / 4, so three heartbeats can go missing before the attempt times out.
_HEARTBEAT_FACTOR = 4


async def _drain_cancelled_body(
    task: asyncio.Task[MetricRecalculationResult],
    deadline: float,
    recalculation_id: str,
    metric_uuid: str,
    attempt: int,
) -> None:
    # sync_to_async cannot stop its worker thread, and returning while it runs leaves the ClickHouse query, its
    # DB connection and the runner's result buffers alive and unsupervised. Kill the query so the thread returns
    # now instead of at max_execution_time, then wait it out until the attempt's own deadline, which the body
    # cannot outlive by design. The kill repeats because it only hits a query ClickHouse has registered, and a
    # cancel during the body's Postgres phase precedes that. It also runs once past the deadline, because it is
    # the cheap part and the thread keeps reading otherwise.
    loop = asyncio.get_running_loop()
    while not task.done():
        try:
            # A kill that hangs must not hold the drain past its deadline. The floor keeps the one kill after it.
            kill_timeout = max(deadline - loop.time(), _CANCEL_KILL_RETRY_INTERVAL_SECONDS)
            await asyncio.wait_for(_cancel_metric_query_sync(recalculation_id, metric_uuid, attempt), kill_timeout)
        except Exception:
            logger.warning(
                "experiment_metric_recalculation_query_cancel_failed",
                metric_uuid=metric_uuid,
                recalculation_id=recalculation_id,
                exc_info=True,
            )
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.warning(
                "experiment_metric_recalculation_drain_after_cancel_timed_out",
                metric_uuid=metric_uuid,
                recalculation_id=recalculation_id,
            )
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=min(_CANCEL_KILL_RETRY_INTERVAL_SECONDS, remaining))
        except TimeoutError:
            continue
        except Exception:
            logger.warning(
                "experiment_metric_recalculation_drain_after_cancel_failed",
                metric_uuid=metric_uuid,
                recalculation_id=recalculation_id,
                exc_info=True,
            )
            return


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
    role: str = "primary",
) -> MetricRecalculationResult:
    """Calculate one metric, write its recalc-fingerprinted result to ExperimentMetricResult, and fold the
    progress update (counter + error) into the same job atomically. query_to is the run's shared data-window end.

    role ("primary" or "secondary") is carried from discovery in ExperimentMetricToRecalculate.role; it's
    threaded into the per-metric PostHog event so the capture path doesn't have to re-query the saved-metric M2M
    to resolve it. Defaults to "primary" so existing call sites and tests that don't pass it remain valid. The
    workflow passes these arguments by position, so recorded histories depend on their order, not their names.

    Finality is derived from activity.info().attempt against MAX_METRIC_ATTEMPTS, the same constant the
    workflow's RetryPolicy is built from, so both sides agree on which attempt is the last. On the final
    attempt a transient failure is persisted rather than re-raised silently, so the row reflects the real
    outcome once Temporal stops retrying. When Temporal ends the metric earlier (the schedule_to_close budget, or a
    kill from the outside), no attempt persists it and the workflow runs record_metric_out_of_time_failure.
    """
    attempt = temporalio.activity.info().attempt
    is_final_attempt = attempt >= MAX_METRIC_ATTEMPTS
    deadline = asyncio.get_running_loop().time() + METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS
    # The heartbeat runs on the event loop beside the body's thread. Temporal delivers a cancellation (a workflow
    # cancel, or a timeout the server enforces) only in a heartbeat response, so the drain below depends on it.
    async with Heartbeater(factor=_HEARTBEAT_FACTOR):
        task = asyncio.ensure_future(
            on_asyncify_pool(_calculate_experiment_metric_for_recalculation_sync)(
                experiment_id, metric_uuid, recalculation_id, query_to, role, is_final_attempt, attempt
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Keep the worker slot while the uncancellable thread finishes, but bound shutdown cleanup.
            drain = asyncio.create_task(_drain_cancelled_body(task, deadline, recalculation_id, metric_uuid, attempt))
            while True:
                try:
                    await asyncio.shield(drain)
                    break
                except asyncio.CancelledError:
                    if drain.cancelled():
                        break
            raise


@temporalio.activity.defn
async def record_metric_out_of_time_failure(failure: MetricOutOfTimeFailure) -> None:
    """Persist the FAILED result and the terminal error event of a metric that Temporal ended from the outside.

    The calc activity persists a failure only when it runs its final attempt to the end. A schedule_to_close budget
    that ends the retries early, or a last attempt killed by start_to_close or heartbeat_timeout, leaves no outcome.
    """
    await _record_metric_out_of_time_failure_sync(failure)
