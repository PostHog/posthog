"""Prometheus metrics for the experiment metrics recalculation workflow.

Follows the established Temporal interceptor pattern (see posthog/temporal/ai_observability/metrics.py).
Emits two latency histograms via ``ExecutionTimeRecorder`` (activity-level, labeled by activity_type;
workflow-level, end-to-end) plus counters for activity success/failure and workflow starts. The histogram
names match ``EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS`` so the bucket boundaries
registered in ``posthog/temporal/common/worker.py`` actually apply.
"""

import typing

from django.conf import settings

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.ai_observability.metrics import ExecutionTimeRecorder

# The workflow type name (matches @workflow.defn(name=...) in recalculation_workflow).
_RECALCULATION_WORKFLOW_TYPE = "experiment-metrics-recalculation-workflow"
# Activity type names (the registered activity function names).
_RECALCULATION_ACTIVITY_TYPES = {
    "discover_experiment_metrics",
    "calculate_experiment_metric_for_recalculation",
    "update_recalculation_progress",
}

EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS = (
    "experiment_metrics_recalculation_activity_execution_latency",
    "experiment_metrics_recalculation_workflow_execution_latency",
)
EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_BUCKETS = [
    100.0,  # 100ms
    500.0,  # 500ms
    1_000.0,  # 1s
    5_000.0,  # 5s
    10_000.0,  # 10s
    30_000.0,  # 30s
    60_000.0,  # 1m
    120_000.0,  # 2m
    300_000.0,  # 5m
]

# Bucket boundaries for `_activity_success_attempts` (counts the attempt number at which success was reached).
# With `RetryPolicy(maximum_attempts=2)` today, only buckets [1, 2] are populated, but the wider range survives
# a future policy change without needing a new histogram.
EXPERIMENT_METRICS_RECALCULATION_ATTEMPT_HISTOGRAM_METRICS = (
    "experiment_metrics_recalculation_activity_success_attempts",
)
EXPERIMENT_METRICS_RECALCULATION_ATTEMPT_HISTOGRAM_BUCKETS = [1.0, 2.0, 5.0, 10.0]


def increment_workflow_finished(status: str) -> None:
    """Workflow-body callsite for the terminal lifecycle counter.

    Emitted from inside `ExperimentMetricsRecalculationWorkflow.run` rather than the interceptor so the
    `status` attribute can be the run's business-level outcome (`"completed"` / `"failed"`, where `"failed"`
    means at least one metric failed). An interceptor-based version would only see exception-vs-no-exception,
    which conflates a 9-of-10-failed run with a healthy one.

    `workflow_type` is attached so dashboards stay scoped when other experiments workflows ship later.
    """
    workflow.metric_meter().with_additional_attributes(
        {"status": status, "workflow_type": _RECALCULATION_WORKFLOW_TYPE}
    ).create_counter(
        "experiment_metrics_recalculation_workflow_finished",
        "Number of experiment metrics recalculation workflows that reached a terminal state.",
    ).add(1)


class _ActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        info = activity.info()
        activity_type = info.activity_type
        if activity_type not in _RECALCULATION_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        meter = activity.metric_meter().with_additional_attributes(
            {"activity_type": activity_type, "workflow_type": _RECALCULATION_WORKFLOW_TYPE}
        )
        # Fires on every attempt (first run + each retry). Comparing this to `_activity_successes` reveals
        # retry rate; without it a transient ClickHouse blip is indistinguishable from a healthy first-try
        # success. Pattern mirrors batch_exports' `batch_exports_activity_attempts`.
        meter.create_counter(
            "experiment_metrics_recalculation_activity_attempts",
            "Number of experiment metrics recalculation activity attempts (each retry is one attempt).",
        ).add(1)

        try:
            with ExecutionTimeRecorder(
                "experiment_metrics_recalculation_activity_execution_latency",
                description="Execution latency for experiment metrics recalculation activities.",
                histogram_attributes={
                    "activity_type": activity_type,
                    "workflow_type": _RECALCULATION_WORKFLOW_TYPE,
                },
            ):
                result = await super().execute_activity(input)
        except Exception:
            meter.create_counter(
                "experiment_metrics_recalculation_activity_failures",
                "Number of failed experiment metrics recalculation activity executions.",
            ).add(1)
            raise
        meter.create_counter(
            "experiment_metrics_recalculation_activity_successes",
            "Number of successful experiment metrics recalculation activity executions.",
        ).add(1)
        # Records the attempt-count distribution for successful runs. info.attempt is 1 on a first-try success
        # and >1 when retries happened before success — `histogram_quantile(0.99, ...)` answers
        # "how often do we need to retry to succeed?". Matches batch_exports' success_attempts pattern.
        meter.create_histogram(
            name="experiment_metrics_recalculation_activity_success_attempts",
            description="Attempt number at which an activity execution succeeded (1 = first try).",
            unit="attempts",
        ).record(info.attempt)
        return result


class _WorkflowInboundInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        if workflow.info().workflow_type != _RECALCULATION_WORKFLOW_TYPE:
            return await super().execute_workflow(input)
        workflow.metric_meter().with_additional_attributes(
            {"workflow_type": _RECALCULATION_WORKFLOW_TYPE}
        ).create_counter(
            "experiment_metrics_recalculation_workflow_started",
            "Number of experiment metrics recalculation workflows started.",
        ).add(1)
        try:
            with ExecutionTimeRecorder(
                "experiment_metrics_recalculation_workflow_execution_latency",
                description="End-to-end execution latency for the experiment metrics recalculation workflow.",
                histogram_attributes={"workflow_type": _RECALCULATION_WORKFLOW_TYPE},
            ):
                return await super().execute_workflow(input)
        except BaseException:
            # The workflow body emits `increment_workflow_finished` immediately before its return statements,
            # so any exception escaping past here means the body's call never ran — no risk of double-count.
            # Without this, hard failures (activity retries exhausted, non-retryable ApplicationError, etc.)
            # increment `_workflow_started` but not `_workflow_finished`, silently under-counting in any
            # `finished / started` success-rate dashboard.
            increment_workflow_finished("failed")
            raise


class ExperimentsRecalculationMetricsInterceptor(Interceptor):
    """Interceptor emitting Prometheus metrics for the experiment metrics recalculation workflow."""

    # Required by `is_task_queue_supported` in `posthog/temporal/common/interceptor.py` — without this attribute
    # the interceptor is filtered out of every worker and the metrics never emit. The recalc workflow + activities
    # are registered on this queue in `posthog/management/commands/start_temporal_worker.py`.
    task_queue = settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _WorkflowInboundInterceptor
