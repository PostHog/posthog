"""Prometheus metrics for the experiment metrics recalculation workflow.

Follows the established Temporal interceptor pattern (see products/batch_exports/backend/temporal/metrics.py).
The latency histograms named in ``EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS`` are emitted by the
Temporal Prometheus runtime once their bucket boundaries are registered in ``posthog/temporal/common/worker.py``.
This interceptor additionally emits success/failure counters that back Grafana dashboards and alert rules.
"""

import typing

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

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


class _ActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_type = activity.info().activity_type
        if activity_type not in _RECALCULATION_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        meter = activity.metric_meter().with_additional_attributes({"activity_type": activity_type})
        try:
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
        return result


class _WorkflowInboundInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        if workflow.info().workflow_type != _RECALCULATION_WORKFLOW_TYPE:
            return await super().execute_workflow(input)
        workflow.metric_meter().create_counter(
            "experiment_metrics_recalculation_workflow_started",
            "Number of experiment metrics recalculation workflows started.",
        ).add(1)
        return await super().execute_workflow(input)


class ExperimentsRecalculationMetricsInterceptor(Interceptor):
    """Interceptor emitting Prometheus metrics for the experiment metrics recalculation workflow."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _WorkflowInboundInterceptor
