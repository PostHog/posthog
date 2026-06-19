import asyncio
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from products.experiments.backend.temporal.models import (
        ExperimentMetricsRecalculationWorkflowInputs,
        ExperimentSingleMetricRetryWorkflowInputs,
        RecalculationProgressUpdate,
    )
    from products.experiments.backend.temporal.recalculation_activities import (
        calculate_experiment_metric_for_recalculation,
        discover_experiment_metrics,
        finalize_single_metric_retry,
        resolve_single_metric_retry_context,
        update_recalculation_progress,
    )
    from products.experiments.backend.temporal.recalculation_metrics import increment_workflow_finished

MAX_CONCURRENT_METRICS = 10


@temporalio.workflow.defn(name="experiment-metrics-recalculation-workflow")
class ExperimentMetricsRecalculationWorkflow(PostHogWorkflow):
    """Recalculate all metrics for an experiment on demand.

    Each run discovers all metrics, marks the job in_progress (which also pins the single data-window end), fans
    out one calc activity per metric with bounded concurrency, then finalizes the job status. Per-metric progress
    counters and errors are folded into the calc activity itself, so the workflow only writes progress at start
    and finish.
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

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_METRICS)

        async def _run_metric(metric):
            async with semaphore:
                return await temporalio.workflow.execute_activity(
                    calculate_experiment_metric_for_recalculation,
                    args=[metric.experiment_id, metric.metric_uuid, recalculation_id, query_to, metric.metric_type],
                    # No heartbeat: the activity's only long-running step is one blocking ClickHouse query
                    # with no progress hooks, so start_to_close_timeout is the real per-attempt ceiling.
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(seconds=5),
                        maximum_interval=timedelta(seconds=30),
                    ),
                )

        results = await asyncio.gather(*[_run_metric(m) for m in metrics], return_exceptions=True)
        succeeded = sum(1 for r in results if not isinstance(r, BaseException) and r.success)
        failed = len(metrics) - succeeded

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


@temporalio.workflow.defn(name="experiment-single-metric-retry-workflow")
class ExperimentSingleMetricRetryWorkflow(PostHogWorkflow):
    """Recompute one failed metric inside an existing recalculation, reusing the run's query_to.

    No discovery/start step: the run already exists with a pinned query_to and metric set. Resolves the metric's
    calc context from the row, runs the same calc activity as the batch flow for the single metric, then
    finalizes (clears the metric's error on success, recomputes run status). The run is never reopened to
    in_progress, so the per-experiment active-run uniqueness constraint is untouched.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExperimentSingleMetricRetryWorkflowInputs:
        return ExperimentSingleMetricRetryWorkflowInputs(recalculation_id=inputs[0], metric_uuid=inputs[1])

    @temporalio.workflow.run
    async def run(self, inputs: ExperimentSingleMetricRetryWorkflowInputs) -> dict:
        recalculation_id = inputs.recalculation_id
        metric_uuid = inputs.metric_uuid

        # Workflows can't touch the DB; read experiment_id / query_to / metric_type via an activity.
        context = await temporalio.workflow.execute_activity(
            resolve_single_metric_retry_context,
            args=[recalculation_id, metric_uuid],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        await temporalio.workflow.execute_activity(
            calculate_experiment_metric_for_recalculation,
            args=[
                context["experiment_id"],
                metric_uuid,
                recalculation_id,
                context["query_to"],
                context["metric_type"],
            ],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(seconds=5),
                maximum_interval=timedelta(seconds=30),
            ),
        )

        await temporalio.workflow.execute_activity(
            finalize_single_metric_retry,
            args=[recalculation_id, metric_uuid],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        temporalio.workflow.logger.info(f"single-metric retry done: recalc {recalculation_id} metric {metric_uuid}")
        return {"recalculation_id": recalculation_id, "metric_uuid": metric_uuid}
