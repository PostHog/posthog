"""Integration tests for the two-phase fan-out workflow.

Mirrors the pattern in `posthog/temporal/tests/test_alerts_workflows.py`:
`WorkflowEnvironment.start_time_skipping()` + `UnsandboxedWorkflowRunner` so
the sandbox doesn't trip on Django imports inside `activities.py`.
"""

import uuid
import asyncio
import logging
from datetime import timedelta

import pytest
from unittest.mock import patch

from temporalio import activity, workflow
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.logs.backend.alert_signal_emitter import NotifiedAlert
from products.logs.backend.temporal.activities import (
    CheckAlertsInput,
    CheckAlertsOutput,
    CohortManifest,
    DiscoverCohortsInput,
    DiscoverCohortsOutput,
    EmitAlertSignalsInput,
    EvaluateCohortBatchInput,
    EvaluateCohortBatchOutput,
)
from products.logs.backend.temporal.workflow import LogsAlertCheckWorkflow

TASK_QUEUE = "logs-alerting-test"


@pytest.mark.parametrize("bounded, fail_first", [(True, False), (True, True), (False, False)])
@pytest.mark.asyncio
async def test_workflow_chunks_manifests_and_aggregates_results(
    bounded: bool, fail_first: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    manifests = [
        CohortManifest(
            team_id=1,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:05:00+00:00",
            alert_ids=[f"alert-{i}"],
        )
        for i in range(25)
    ]
    releases = {f"alert-{i}": asyncio.Event() for i in range(0, 25, 3)}
    started: asyncio.Queue[str] = asyncio.Queue()
    received: list[CohortManifest] = []
    failed_batch_id: str | None = None

    @activity.defn(name="discover_cohorts_activity")
    async def fake_discover(_input: DiscoverCohortsInput) -> DiscoverCohortsOutput:
        return DiscoverCohortsOutput(manifests=manifests, batch_size=3)

    @activity.defn(name="evaluate_cohort_batch_activity")
    async def fake_evaluate(input: EvaluateCohortBatchInput) -> EvaluateCohortBatchOutput:
        batch_id = input.manifests[0].alert_ids[0]
        received.extend(input.manifests)
        started.put_nowait(batch_id)
        await releases[batch_id].wait()
        if batch_id == failed_batch_id:
            raise ApplicationError("simulated batch failure", non_retryable=True)
        return EvaluateCohortBatchOutput(
            alerts_checked=len(input.manifests),
            alerts_fired=0,
            alerts_resolved=0,
            alerts_errored=0,
        )

    original_patched = workflow.patched
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with patch.object(workflow, "patched", side_effect=lambda name: bounded and original_patched(name)):
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[LogsAlertCheckWorkflow],
                activities=[fake_discover, fake_evaluate],
                workflow_runner=UnsandboxedWorkflowRunner(),
                max_concurrent_activities=16,
            ):
                handle = await env.client.start_workflow(
                    LogsAlertCheckWorkflow.run,
                    CheckAlertsInput(),
                    id=f"test-workflow-aggregate-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                    execution_timeout=timedelta(minutes=2),
                )
                try:
                    initial_count = 8 if bounded else 9
                    initial_batches = [await asyncio.wait_for(started.get(), timeout=30) for _ in range(initial_count)]
                    history = await handle.fetch_history()
                    assert (
                        sum(
                            event.activity_task_scheduled_event_attributes.activity_type.name
                            == "evaluate_cohort_batch_activity"
                            for event in history.events
                            if event.HasField("activity_task_scheduled_event_attributes")
                        )
                        == initial_count
                    )

                    first_batch = initial_batches[0]
                    failed_batch_id = first_batch if fail_first else None
                    releases[first_batch].set()
                    if bounded:
                        next_batch = await asyncio.wait_for(started.get(), timeout=30)
                        assert next_batch not in initial_batches
                        assert all(not releases[batch_id].is_set() for batch_id in initial_batches[1:])
                finally:
                    for release in releases.values():
                        release.set()
                result: CheckAlertsOutput = await handle.result()
                history = await handle.fetch_history()

        await Replayer(workflows=[LogsAlertCheckWorkflow], workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(
            history
        )

    assert sorted(received, key=lambda manifest: manifest.alert_ids[0]) == sorted(
        manifests, key=lambda manifest: manifest.alert_ids[0]
    )
    assert result.alerts_checked == (22 if fail_first else 25)
    assert result.alerts_errored == (3 if fail_first else 0)


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


def _single_manifest() -> list[CohortManifest]:
    return [
        CohortManifest(
            team_id=1,
            projection_eligible=True,
            date_to_iso="2026-05-05T10:05:00+00:00",
            alert_ids=["x"],
        )
    ]


@pytest.mark.asyncio
async def test_workflow_forwards_notified_alerts_to_emission_activity() -> None:
    manifests = _single_manifest()

    @activity.defn(name="discover_cohorts_activity")
    async def fake_discover(_input: DiscoverCohortsInput) -> DiscoverCohortsOutput:
        return DiscoverCohortsOutput(manifests=manifests, batch_size=20)

    @activity.defn(name="evaluate_cohort_batch_activity")
    async def fake_evaluate(input: EvaluateCohortBatchInput) -> EvaluateCohortBatchOutput:
        return EvaluateCohortBatchOutput(
            alerts_checked=1,
            alerts_fired=1,
            alerts_resolved=0,
            alerts_errored=0,
            notified=[
                NotifiedAlert(
                    alert_id="x",
                    team_id=1,
                    alert_name="A",
                    action="firing",
                    weight=1.0,
                    threshold_count=1,
                    threshold_operator="above",
                    window_minutes=5,
                    result_count=9,
                    consecutive_failures=0,
                    filters={},
                )
            ],
        )

    captured: dict = {}

    @activity.defn(name="emit_alert_signals_activity")
    async def fake_emit(input: EmitAlertSignalsInput) -> int:
        captured["count"] = len(input.notified)
        captured["action"] = input.notified[0].action
        return len(input.notified)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LogsAlertCheckWorkflow],
            activities=[fake_discover, fake_evaluate, fake_emit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                LogsAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id=f"test-workflow-emit-signals-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert captured["count"] == 1
    assert captured["action"] == "firing"


@pytest.mark.asyncio
async def test_workflow_skips_emission_activity_when_no_alerts_notified() -> None:
    manifests = _single_manifest()

    @activity.defn(name="discover_cohorts_activity")
    async def fake_discover(_input: DiscoverCohortsInput) -> DiscoverCohortsOutput:
        return DiscoverCohortsOutput(manifests=manifests, batch_size=20)

    @activity.defn(name="evaluate_cohort_batch_activity")
    async def fake_evaluate(input: EvaluateCohortBatchInput) -> EvaluateCohortBatchOutput:
        # No notified alerts this cycle.
        return EvaluateCohortBatchOutput(alerts_checked=1, alerts_fired=0, alerts_resolved=0, alerts_errored=0)

    emit_called = {"n": 0}

    @activity.defn(name="emit_alert_signals_activity")
    async def fake_emit(input: EmitAlertSignalsInput) -> int:
        emit_called["n"] += 1
        return 0

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LogsAlertCheckWorkflow],
            activities=[fake_discover, fake_evaluate, fake_emit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                LogsAlertCheckWorkflow.run,
                CheckAlertsInput(),
                id=f"test-workflow-no-signals-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert emit_called["n"] == 0
