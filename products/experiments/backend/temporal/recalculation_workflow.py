import asyncio
from datetime import timedelta

import temporalio.workflow
from temporalio.common import Priority, RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    RetryState,
    TimeoutError as TemporalTimeoutError,
)

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.models import (
        MAX_METRIC_ATTEMPTS,
        METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS,
        METRIC_CALC_HEARTBEAT_TIMEOUT_SECONDS,
        METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS,
        METRIC_FAILURE_BACKSTOP_ACTIVITY_TIMEOUT_SECONDS,
        METRIC_FAILURE_BACKSTOP_MAX_ATTEMPTS,
        METRIC_FAILURE_BACKSTOP_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS,
        METRICS_RECALCULATION_WORKFLOW_NAME,
        RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS,
        RECALCULATION_PROGRESS_MAX_ATTEMPTS,
        RECALCULATION_RETRY_BACKOFF_COEFFICIENT,
        RECALCULATION_RETRY_INITIAL_INTERVAL_SECONDS,
        RECALCULATION_RETRY_MAX_INTERVAL_SECONDS,
        ExperimentMetricsRecalculationWorkflowInputs,
        ExperimentMetricToRecalculate,
        MetricOutOfTimeFailure,
        RecalculationProgressUpdate,
    )
    from products.experiments.backend.temporal.recalculation_activities import (
        calculate_experiment_metric_for_recalculation,
        discover_experiment_metrics,
        record_metric_out_of_time_failure,
        update_recalculation_progress,
    )
    from products.experiments.backend.temporal.recalculation_metrics import increment_workflow_finished


def _ended_by_temporal(error: ActivityError) -> bool:
    """True when Temporal ended the metric's retries from the outside, so no attempt persisted its outcome.

    A timeout cause is an attempt killed by start_to_close, heartbeat_timeout or schedule_to_close. A TIMEOUT retry
    state is an attempt that raised a retryable error when the schedule_to_close budget had no room for another.
    """
    return error.retry_state == RetryState.TIMEOUT or isinstance(error.cause, TemporalTimeoutError)


@temporalio.workflow.defn(name=METRICS_RECALCULATION_WORKFLOW_NAME)
class ExperimentMetricsRecalculationWorkflow(PostHogWorkflow):
    """Recalculate all metrics for an experiment on demand.

    Each run discovers all metrics, marks the job in_progress (which also pins the single data-window end),
    schedules one calc activity per metric all at once, and finalizes the job status. The workflow imposes no
    concurrency of its own, pacing is owned by the layers that actually constrain it: worker activity slots
    (MAX_CONCURRENT_ACTIVITIES, autoscaled on task queue backlog) bound compute, and the per-org ClickHouse
    app-query limiter bounds query fan-out. Scheduling every metric up front also keeps the task queue backlog
    honest for the autoscaler. Per-metric progress counters and errors are folded into the calc activity
    itself, so the workflow only writes progress at start and finish.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentMetricsRecalculationWorkflowInputs:
        return ExperimentMetricsRecalculationWorkflowInputs(recalculation_id=inputs[0])

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentMetricsRecalculationWorkflowInputs) -> dict:
        try:
            return await self._run_recalculation(inputs)
        except Exception:
            if temporalio.workflow.patched("recalc-terminal-fail-on-error-2026-07"):
                await self._best_effort_mark_terminal(inputs.recalculation_id, status="failed")
            raise

    async def _run_recalculation(self, inputs: ExperimentMetricsRecalculationWorkflowInputs) -> dict:
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
                start_to_close_timeout=timedelta(seconds=RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=RECALCULATION_PROGRESS_MAX_ATTEMPTS),
            )
            try:
                await temporalio.workflow.execute_activity(
                    update_recalculation_progress,
                    RecalculationProgressUpdate(
                        recalculation_id=recalculation_id,
                        status="completed",
                        mark_completed=True,
                    ),
                    start_to_close_timeout=timedelta(seconds=RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS),
                    retry_policy=RetryPolicy(maximum_attempts=RECALCULATION_PROGRESS_MAX_ATTEMPTS),
                )
            except Exception:
                # A zero-metric run genuinely completed; record that via the backstop rather than letting run()'s
                # except mislabel it failed. If the backstop also fails (or the patch is off), re-raise so the
                # workflow fails instead of reporting success on a non-terminal row.
                recorded = temporalio.workflow.patched("recalc-terminal-fail-on-error-2026-07") and (
                    await self._best_effort_mark_terminal(recalculation_id, status="completed", succeeded=0, failed=0)
                )
                if not recorded:
                    raise

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
            start_to_close_timeout=timedelta(seconds=RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=RECALCULATION_PROGRESS_MAX_ATTEMPTS),
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

        calc_retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=RECALCULATION_RETRY_INITIAL_INTERVAL_SECONDS),
            backoff_coefficient=RECALCULATION_RETRY_BACKOFF_COEFFICIENT,
            maximum_interval=timedelta(seconds=RECALCULATION_RETRY_MAX_INTERVAL_SECONDS),
            maximum_attempts=MAX_METRIC_ATTEMPTS,
        )
        # Pre-patch histories scheduled every calculation on the workflow's queue, even when an old worker
        # received a run with the field set, so they must replay with None.
        activity_task_queue = (
            inputs.activity_task_queue
            if inputs.activity_task_queue and temporalio.workflow.patched("recalc-activity-task-queue-2026-10")
            else None
        )
        results = await asyncio.gather(
            *[
                temporalio.workflow.execute_activity(
                    calculate_experiment_metric_for_recalculation,
                    args=[
                        metric.experiment_id,
                        metric.metric_uuid,
                        recalculation_id,
                        query_to,
                        metric.role,
                    ],
                    start_to_close_timeout=timedelta(seconds=METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS),
                    schedule_to_close_timeout=timedelta(seconds=METRIC_CALC_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS),
                    heartbeat_timeout=timedelta(seconds=METRIC_CALC_HEARTBEAT_TIMEOUT_SECONDS),
                    retry_policy=calc_retry_policy,
                    task_queue=activity_task_queue,
                    # Round-robin dispatch across orgs under backlog; a no-op on namespaces without
                    # fairness support.
                    priority=Priority(fairness_key=inputs.fairness_key),
                )
                for metric in metrics
            ],
            return_exceptions=True,
        )

        out_of_time = [
            metric
            for metric, result in zip(metrics, results)
            if isinstance(result, ActivityError) and _ended_by_temporal(result)
        ]
        if out_of_time and temporalio.workflow.patched("recalc-persist-out-of-time-metrics-2026-10"):
            await self._record_out_of_time_failures(recalculation_id, out_of_time)

        succeeded = sum(1 for result in results if not isinstance(result, BaseException) and result.success)
        failed = len(results) - succeeded
        final_status = "failed" if failed > 0 else "completed"

        try:
            await temporalio.workflow.execute_activity(
                update_recalculation_progress,
                RecalculationProgressUpdate(
                    recalculation_id=recalculation_id,
                    status=final_status,
                    mark_completed=True,
                    succeeded_metrics=succeeded,
                    failed_metrics=failed,
                ),
                start_to_close_timeout=timedelta(seconds=RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=RECALCULATION_PROGRESS_MAX_ATTEMPTS),
            )
        except Exception:
            # The finalize write exhausted its retries. Record the real status/counts via the backstop so the
            # row still goes terminal. If the backstop also fails (or the patch is disabled for a replaying
            # older execution), re-raise: the workflow must fail rather than report success on a non-terminal
            # row, and the interceptor + staleness TTL take over as before.
            recorded = temporalio.workflow.patched("recalc-terminal-fail-on-error-2026-07") and (
                await self._best_effort_mark_terminal(
                    recalculation_id, status=final_status, succeeded=succeeded, failed=failed
                )
            )
            if not recorded:
                raise

        temporalio.workflow.logger.info(
            f"recalc {recalculation_id} finished: {succeeded} succeeded, {failed} failed (status={final_status})"
        )
        increment_workflow_finished(final_status)
        return {"total": len(metrics), "succeeded": succeeded, "failed": failed}

    async def _record_out_of_time_failures(
        self, recalculation_id: str, metrics: list[ExperimentMetricToRecalculate]
    ) -> None:
        # Best effort: a backstop failure must not stop the finish step, which still counts these metrics failed.
        await asyncio.gather(
            *[
                temporalio.workflow.execute_activity(
                    record_metric_out_of_time_failure,
                    MetricOutOfTimeFailure(
                        recalculation_id=recalculation_id,
                        experiment_id=metric.experiment_id,
                        metric_uuid=metric.metric_uuid,
                        role=metric.role,
                    ),
                    start_to_close_timeout=timedelta(seconds=METRIC_FAILURE_BACKSTOP_ACTIVITY_TIMEOUT_SECONDS),
                    schedule_to_close_timeout=timedelta(
                        seconds=METRIC_FAILURE_BACKSTOP_SCHEDULE_TO_CLOSE_TIMEOUT_SECONDS
                    ),
                    retry_policy=RetryPolicy(maximum_attempts=METRIC_FAILURE_BACKSTOP_MAX_ATTEMPTS),
                )
                for metric in metrics
            ],
            return_exceptions=True,
        )

    async def _best_effort_mark_terminal(
        self, recalculation_id: str, *, status: str, succeeded: int | None = None, failed: int | None = None
    ) -> bool:
        # Returns True if the terminal write landed, False if it too exhausted its retries. Callers that need
        # the row to be terminal (the finalize-failure path) re-raise on False so the run still fails and the
        # staleness TTL reaps it; the pre-finalize caller re-raises the original exception regardless.
        try:
            await temporalio.workflow.execute_activity(
                update_recalculation_progress,
                RecalculationProgressUpdate(
                    recalculation_id=recalculation_id,
                    status=status,
                    mark_completed=True,
                    succeeded_metrics=succeeded,
                    failed_metrics=failed,
                ),
                start_to_close_timeout=timedelta(seconds=RECALCULATION_PROGRESS_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=RECALCULATION_PROGRESS_MAX_ATTEMPTS),
            )
            return True
        except Exception:
            temporalio.workflow.logger.exception(
                f"recalc {recalculation_id} failed to record terminal status; staleness TTL will reap it"
            )
            return False
