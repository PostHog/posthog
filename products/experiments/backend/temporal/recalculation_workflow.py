import asyncio
import dataclasses
from collections import deque
from datetime import datetime, timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.models import (
        MAX_METRIC_ATTEMPTS,
        METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS,
        ExperimentMetricsRecalculationWorkflowInputs,
        ExperimentMetricToRecalculate,
        RecalculationProgressUpdate,
    )
    from products.experiments.backend.temporal.recalculation_activities import (
        calculate_experiment_metric_for_recalculation,
        discover_experiment_metrics,
        update_recalculation_progress,
    )
    from products.experiments.backend.temporal.recalculation_metrics import increment_workflow_finished

# Per-run metric fan-out: how many metric activities one run keeps in flight, sized so a typical experiment
# recalculates in a single concurrent wave. Cross-run ClickHouse load is bounded separately by the dedicated
# recalc worker's activity-slot cap (MAX_CONCURRENT_ACTIVITIES), not by this constant.
MAX_CONCURRENT_METRICS = 14


@temporalio.workflow.defn(name="experiment-metrics-recalculation-workflow")
class ExperimentMetricsRecalculationWorkflow(PostHogWorkflow):
    """Recalculate all metrics for an experiment on demand.

    Each run discovers all metrics, marks the job in_progress (which also pins the single data-window end), then
    runs a pool of MAX_CONCURRENT_METRICS workers draining a requeue queue (one activity attempt at a time;
    transient failures requeue with backoff, the workflow owns retries), and finalizes the job status. Per-metric
    progress counters and errors are folded into the calc activity itself, so the workflow only writes progress
    at start and finish.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentMetricsRecalculationWorkflowInputs:
        return ExperimentMetricsRecalculationWorkflowInputs(recalculation_id=inputs[0])

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentMetricsRecalculationWorkflowInputs) -> dict:
        recalculation_id = inputs.recalculation_id

        metrics = await temporalio.workflow.execute_activity(
            discover_experiment_metrics,
            recalculation_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not metrics:
            # mark_started and mark_completed are mutually exclusive per the activity's XOR contract;
            # for a zero-metric run, start and finish are two sequential calls.
            await temporalio.workflow.execute_activity(
                update_recalculation_progress,
                RecalculationProgressUpdate(
                    recalculation_id=recalculation_id,
                    status="in_progress",
                    total_metrics=0,
                    metric_uuids=[],
                    mark_started=True,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            await temporalio.workflow.execute_activity(
                update_recalculation_progress,
                RecalculationProgressUpdate(
                    recalculation_id=recalculation_id,
                    status="completed",
                    mark_completed=True,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            temporalio.workflow.logger.info(f"recalc {recalculation_id} had no metrics; completing immediately")
            increment_workflow_finished("completed")
            return {"total": 0, "succeeded": 0, "failed": 0}

        # Start the run: mark in_progress, persist the metric list, and pin the shared data-window end. The start
        # activity returns that query_to so every calc activity below uses the exact same window.
        query_to = await temporalio.workflow.execute_activity(
            update_recalculation_progress,
            RecalculationProgressUpdate(
                recalculation_id=recalculation_id,
                status="in_progress",
                total_metrics=len(metrics),
                metric_uuids=[m.metric_uuid for m in metrics],
                mark_started=True,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        # The activity returns Optional[str] in general, but with mark_started=True it always returns the ISO
        # query_to string. Narrow with a real check (not assert, which is stripped under python -O) so calc
        # activities receive a typed str.
        if not isinstance(query_to, str):
            raise ApplicationError(
                f"start activity for recalc {recalculation_id} returned {type(query_to).__name__}, expected str",
                non_retryable=True,
            )

        temporalio.workflow.logger.info(f"running recalc {recalculation_id} with {len(metrics)} metrics")

        # Worker pool over a requeue queue. Retries are owned by the workflow, not the activity's retry policy,
        # so a failing attempt frees its concurrency slot the moment it fails instead of holding it through the
        # whole backoff chain (which would starve healthy metrics behind it). Each activity runs with
        # maximum_attempts=1; on a transient failure (the activity raises) the metric is requeued at the BACK
        # with a not-before delay, so other metrics run before its next attempt. A metric is permanently failed
        # only after MAX_METRIC_ATTEMPTS trips. Permanent failures (StatisticError/ZeroDivisionError) are
        # returned with success=False, not raised, so they terminate on the first trip.
        #
        # Determinism: all time comes from temporalio.workflow.now() (recorded by Temporal, stable on replay)
        # and waits use temporalio.workflow.sleep(); no wall-clock, no Math.random, no host state.
        @dataclasses.dataclass
        class _QueuedMetric:
            metric: ExperimentMetricToRecalculate
            attempts: int  # attempts already made (0 on first enqueue)
            not_before: datetime  # earliest workflow time this item may run

        def _backoff(attempts: int) -> timedelta:
            # Same schedule the old activity retry policy used: 5s, 10s, 20s, 40s, capped at 60s.
            return timedelta(seconds=min(5.0 * (2.0 ** (attempts - 1)), 60.0))

        start_now = temporalio.workflow.now()
        queue: deque[_QueuedMetric] = deque(_QueuedMetric(metric=m, attempts=0, not_before=start_now) for m in metrics)
        succeeded = 0
        failed = 0
        in_flight = 0

        # Re-evaluated by Temporal until true: either an item is queued again (a sibling requeued a retry) or
        # all in-flight work has drained (so this worker can exit). Defined once, not per loop iteration.
        def _queue_changed() -> bool:
            return bool(queue) or in_flight == 0

        async def _worker() -> None:
            nonlocal succeeded, failed, in_flight
            while queue or in_flight:
                if not queue:
                    # Work is still running in a sibling worker but nothing is runnable here yet. Wait on the
                    # in-flight work rather than busy-spin; it will requeue or finish, then re-check.
                    await temporalio.workflow.wait_condition(_queue_changed)
                    continue

                item = queue.popleft()
                wait = (item.not_before - temporalio.workflow.now()).total_seconds()
                if wait > 0:
                    # Not due yet. Requeue and, if every queued item is also not yet due, sleep until this one
                    # is (bounded by its own not_before) so we neither busy-spin nor oversleep past a due item.
                    queue.append(item)
                    if all((q.not_before - temporalio.workflow.now()).total_seconds() > 0 for q in queue):
                        await temporalio.workflow.sleep(timedelta(seconds=wait))
                    continue

                attempt_number = item.attempts + 1
                is_final_attempt = attempt_number >= MAX_METRIC_ATTEMPTS
                in_flight += 1
                try:
                    result = await temporalio.workflow.execute_activity(
                        calculate_experiment_metric_for_recalculation,
                        args=[
                            item.metric.experiment_id,
                            item.metric.metric_uuid,
                            recalculation_id,
                            query_to,
                            item.metric.metric_type,
                            is_final_attempt,
                        ],
                        # No heartbeat: the activity's only long-running step is one blocking ClickHouse query
                        # with no progress hooks, so start_to_close_timeout is the real per-attempt ceiling.
                        # The query's ClickHouse max_execution_time is capped below this (see models.py) so
                        # slow queries fail typed inside the activity instead of being killed from outside.
                        start_to_close_timeout=timedelta(seconds=METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS),
                        # One attempt per invocation; the workflow owns requeue + backoff (see block comment).
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except Exception:
                    # Transient failure (the activity raised). Requeue at the back with a backoff delay unless
                    # this was the final attempt — in which case the activity already persisted the failure.
                    if is_final_attempt:
                        failed += 1
                    else:
                        queue.append(
                            _QueuedMetric(
                                metric=item.metric,
                                attempts=attempt_number,
                                not_before=temporalio.workflow.now() + _backoff(attempt_number),
                            )
                        )
                else:
                    # Returned a result: success, or a permanent failure recorded with success=False.
                    if result.success:
                        succeeded += 1
                    else:
                        failed += 1
                finally:
                    in_flight -= 1

        await asyncio.gather(*[_worker() for _ in range(MAX_CONCURRENT_METRICS)])

        # Any failure marks the run as "failed"; the succeeded/failed counts carry the partial-vs-total nuance
        # for consumers that need it (the UI shows "N succeeded, M failed" alongside the status). A status-only
        # check then can't mistake a 9-of-10-failed run for a healthy one.
        final_status = "failed" if failed > 0 else "completed"
        await temporalio.workflow.execute_activity(
            update_recalculation_progress,
            RecalculationProgressUpdate(
                recalculation_id=recalculation_id,
                status=final_status,
                mark_completed=True,
                succeeded_metrics=succeeded,
                failed_metrics=failed,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        temporalio.workflow.logger.info(
            f"recalc {recalculation_id} finished: {succeeded} succeeded, {failed} failed (status={final_status})"
        )
        increment_workflow_finished(final_status)
        return {"total": len(metrics), "succeeded": succeeded, "failed": failed}
