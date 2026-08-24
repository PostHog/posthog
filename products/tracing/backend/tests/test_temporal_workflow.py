"""Integration test for the tracing alert check workflow's two-phase fan-out.

Mirrors the pattern in `products/logs/backend/test/test_logs_alerting_workflow.py`:
`WorkflowEnvironment.start_time_skipping()` + `UnsandboxedWorkflowRunner` so the
sandbox doesn't trip on Django imports inside `activities.py`.
"""

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tracing.backend.temporal.activities import (
    CheckAlertsInput,
    CheckAlertsOutput,
    DiscoverDueAlertsInput,
    DiscoverDueAlertsOutput,
    EvaluateAlertBatchInput,
    EvaluateAlertBatchOutput,
)
from products.tracing.backend.temporal.workflow import TracingAlertCheckWorkflow

TASK_QUEUE = "tracing-alerting-test"


@pytest.mark.asyncio
async def test_workflow_chunks_alert_ids_and_aggregates_results() -> None:
    # 7 alert ids, batch_size=3 → 3 batches: sizes 3, 3, 1.
    alert_ids = [f"alert-{i}" for i in range(7)]

    @activity.defn(name="discover_due_tracing_alerts_activity")
    async def fake_discover(_input: DiscoverDueAlertsInput) -> DiscoverDueAlertsOutput:
        return DiscoverDueAlertsOutput(alert_ids=alert_ids, batch_size=3)

    @activity.defn(name="evaluate_alert_batch_activity")
    async def fake_evaluate(input: EvaluateAlertBatchInput) -> EvaluateAlertBatchOutput:
        return EvaluateAlertBatchOutput(
            alerts_checked=len(input.alert_ids),
            alerts_fired=1 if input.alert_ids else 0,
            alerts_resolved=0,
            alerts_errored=0,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[TracingAlertCheckWorkflow],
            activities=[fake_discover, fake_evaluate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result: CheckAlertsOutput = await env.client.execute_workflow(
                TracingAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id="test-tracing-alert-check",
                task_queue=TASK_QUEUE,
            )

    assert result.alerts_checked == 7
    assert result.alerts_fired == 3  # one per non-empty batch
    assert result.alerts_resolved == 0
    assert result.alerts_errored == 0


@pytest.mark.asyncio
async def test_workflow_returns_zeros_when_nothing_is_due() -> None:
    @activity.defn(name="discover_due_tracing_alerts_activity")
    async def fake_discover(_input: DiscoverDueAlertsInput) -> DiscoverDueAlertsOutput:
        return DiscoverDueAlertsOutput(alert_ids=[], batch_size=20)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[TracingAlertCheckWorkflow],
            activities=[fake_discover],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result: CheckAlertsOutput = await env.client.execute_workflow(
                TracingAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id="test-tracing-alert-check-empty",
                task_queue=TASK_QUEUE,
            )

    assert result == CheckAlertsOutput(alerts_checked=0, alerts_fired=0, alerts_resolved=0, alerts_errored=0)


@pytest.mark.asyncio
async def test_workflow_counts_failed_batch_as_errored_without_aborting_cycle() -> None:
    alert_ids = ["alert-0", "alert-1", "alert-2", "alert-3"]

    @activity.defn(name="discover_due_tracing_alerts_activity")
    async def fake_discover(_input: DiscoverDueAlertsInput) -> DiscoverDueAlertsOutput:
        return DiscoverDueAlertsOutput(alert_ids=alert_ids, batch_size=2)

    @activity.defn(name="evaluate_alert_batch_activity")
    async def fake_evaluate(input: EvaluateAlertBatchInput) -> EvaluateAlertBatchOutput:
        if "alert-2" in input.alert_ids:
            raise ApplicationError("boom", non_retryable=True)
        return EvaluateAlertBatchOutput(
            alerts_checked=len(input.alert_ids), alerts_fired=0, alerts_resolved=0, alerts_errored=0
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[TracingAlertCheckWorkflow],
            activities=[fake_discover, fake_evaluate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result: CheckAlertsOutput = await env.client.execute_workflow(
                TracingAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id="test-tracing-alert-check-partial-failure",
                task_queue=TASK_QUEUE,
            )

    # Batch [alert-0, alert-1] succeeds (checked=2); batch [alert-2, alert-3] fails
    # after retries exhaust, counting both its alerts as errored.
    assert result.alerts_checked == 2
    assert result.alerts_errored == 2
