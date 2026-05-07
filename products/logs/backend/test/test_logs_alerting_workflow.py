"""Integration tests for the two-phase fan-out workflow.

Mirrors the pattern in `posthog/temporal/tests/test_alerts_workflows.py`:
`WorkflowEnvironment.start_time_skipping()` + `UnsandboxedWorkflowRunner` so
the sandbox doesn't trip on Django imports inside `activities.py`.
"""

import uuid

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.logs.backend.temporal.activities import (
    CheckAlertsInput,
    CheckAlertsOutput,
    CohortManifest,
    DiscoverCohortsInput,
    DiscoverCohortsOutput,
    EvaluateCohortBatchInput,
    EvaluateCohortBatchOutput,
)
from products.logs.backend.temporal.workflow import LogsAlertCheckWorkflow

TASK_QUEUE = "logs-alerting-test"


@pytest.mark.asyncio
async def test_workflow_chunks_manifests_and_aggregates_results() -> None:
    # 7 manifests, batch_size=3 → 3 batches: sizes 3, 3, 1.
    manifests = [
        CohortManifest(
            team_id=1,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:05:00+00:00",
            alert_ids=[f"alert-{i}"],
        )
        for i in range(7)
    ]

    @activity.defn(name="discover_cohorts_activity")
    async def fake_discover(_input: DiscoverCohortsInput) -> DiscoverCohortsOutput:
        return DiscoverCohortsOutput(manifests=manifests, batch_size=3)

    @activity.defn(name="evaluate_cohort_batch_activity")
    async def fake_evaluate(input: EvaluateCohortBatchInput) -> EvaluateCohortBatchOutput:
        return EvaluateCohortBatchOutput(
            alerts_checked=len(input.manifests),
            alerts_fired=0,
            alerts_resolved=0,
            alerts_errored=0,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LogsAlertCheckWorkflow],
            activities=[fake_discover, fake_evaluate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result: CheckAlertsOutput = await env.client.execute_workflow(
                LogsAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id=f"test-workflow-aggregate-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert result.alerts_checked == 7
    assert result.alerts_errored == 0


@pytest.mark.asyncio
async def test_workflow_isolates_per_batch_failure() -> None:
    # One batch's retries exhaust → its alerts count as errored.
    # Other batches' results still aggregate. Workflow does NOT fail.
    manifests = [
        CohortManifest(
            team_id=1,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:05:00+00:00",
            alert_ids=[f"a-{i}", f"b-{i}"],  # 2 alerts per cohort
        )
        for i in range(4)
    ]

    @activity.defn(name="discover_cohorts_activity")
    async def fake_discover(_input: DiscoverCohortsInput) -> DiscoverCohortsOutput:
        return DiscoverCohortsOutput(manifests=manifests, batch_size=2)

    # 4 cohorts ÷ batch=2 → 2 batches. Second batch always fails.
    call_count = {"n": 0}

    @activity.defn(name="evaluate_cohort_batch_activity")
    async def fake_evaluate(input: EvaluateCohortBatchInput) -> EvaluateCohortBatchOutput:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise ApplicationError("simulated batch failure", non_retryable=True)
        return EvaluateCohortBatchOutput(
            alerts_checked=sum(len(m.alert_ids) for m in input.manifests),
            alerts_fired=0,
            alerts_resolved=0,
            alerts_errored=0,
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LogsAlertCheckWorkflow],
            activities=[fake_discover, fake_evaluate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result: CheckAlertsOutput = await env.client.execute_workflow(
                LogsAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id=f"test-workflow-partial-fail-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    # Successful batch: 2 cohorts × 2 alerts = 4 alerts checked.
    # Failed batch: 2 cohorts × 2 alerts = 4 alerts counted as errored.
    assert result.alerts_checked == 4
    assert result.alerts_errored == 4
