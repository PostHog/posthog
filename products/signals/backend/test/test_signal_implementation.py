from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.signal_handoffs import SignalHandoff
from products.signals.backend.temporal.report_safety_judge import (
    SafetyJudgeInput,
    SafetyJudgeResponse,
    report_safety_judge_activity,
)
from products.signals.backend.temporal.signal_implementation import (
    FinalizedSignal,
    SignalImplementationFinalizerWorkflow,
    SignalImplementationInput,
    check_implementation_task_workflow_closed_activity,
    finalize_signal_implementation_activity,
)
from products.signals.backend.temporal.signal_queries import WaitForClickHouseInput
from products.signals.backend.temporal.types import SignalData


@pytest.mark.asyncio
async def test_finalizer_costs_once_after_task_workflow_closes() -> None:
    handoff = SignalHandoff(
        team_id=1,
        signal=SignalData(
            signal_id="signal-id",
            content="content",
            source_product="signals",
            source_type="test",
            source_id="source-id",
            weight=1.0,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        embedding=[],
    )
    workflow_handle = MagicMock(
        describe=AsyncMock(return_value=SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED))
    )
    client = MagicMock(get_workflow_handle=MagicMock(return_value=workflow_handle))
    run = SimpleNamespace(workflow_id="task-workflow", task_id="task-id")
    spend = SimpleNamespace(token_cost=10, compute_cost=20)

    def async_boundary(fn, **_kwargs):
        async def call(*args, **kwargs):
            return fn(*args, **kwargs)

        return call

    with (
        patch("products.signals.backend.temporal.signal_implementation.database_sync_to_async", async_boundary),
        patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=run),
        patch("products.signals.backend.temporal.signal_implementation.get_task_spend", return_value=spend),
        patch("products.signals.backend.temporal.signal_implementation.async_connect", AsyncMock(return_value=client)),
        patch("products.signals.backend.temporal.signal_implementation.read_handoff", AsyncMock(return_value=handoff)),
        patch("products.signals.backend.temporal.signal_implementation.write_handoff", AsyncMock()) as write_handoff,
        patch("products.signals.backend.temporal.signal_implementation.publish_handoff", AsyncMock()),
    ):
        input = SignalImplementationInput(team_id=1, signal_key="handoff", task_id="task-id", run_id="run-id")
        assert await check_implementation_task_workflow_closed_activity(input)
        await finalize_signal_implementation_activity(input)
        await finalize_signal_implementation_activity(input)

    workflow_handle.describe.assert_awaited_once()
    assert handoff.costed_tasks == ["task-id"]
    assert handoff.signal.metadata["token_cost"]["implementation"] == 10
    assert handoff.signal.metadata["compute_cost"]["implementation"] == 20
    assert write_handoff.await_count == 2


@pytest.mark.asyncio
async def test_finalizer_workflow_polls_until_closed_then_publishes() -> None:
    check_answers = iter([False, True])
    published_inputs: list[SignalImplementationInput] = []
    wait_inputs = []

    @activity.defn(name="check_implementation_task_workflow_closed_activity")
    async def check_closed(input: SignalImplementationInput) -> bool:
        return next(check_answers)

    @activity.defn(name="finalize_signal_implementation_activity")
    async def finalize(input: SignalImplementationInput) -> list[FinalizedSignal]:
        published_inputs.append(input)
        return [FinalizedSignal(signal_id="signal-id", timestamp=datetime(2026, 1, 1, tzinfo=UTC))]

    @activity.defn(name="wait_for_signal_in_clickhouse_activity")
    async def wait_for_clickhouse(input: WaitForClickHouseInput) -> None:
        wait_inputs.append(input)

    @activity.defn(name="release_signal_key_activity")
    async def release(input: SignalImplementationInput) -> None:
        return None

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="signal-implementation-test",
            workflows=[SignalImplementationFinalizerWorkflow],
            activities=[check_closed, finalize, wait_for_clickhouse, release],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                SignalImplementationFinalizerWorkflow.run,
                SignalImplementationInput(team_id=1, signal_key="owner", run_id="run-id"),
                id="signal-implementation-finalizer-test",
                task_queue="signal-implementation-test",
            )

    assert len(published_inputs) == 1
    assert len(wait_inputs) == 1
    assert [signal.signal_id for signal in wait_inputs[0].signals] == ["signal-id"]


@pytest.mark.asyncio
async def test_finalizer_workflow_waits_once_for_a_signal_batch() -> None:
    signal_keys = [f"signal-{index}" for index in range(20)]
    wait_inputs: list[WaitForClickHouseInput] = []

    @activity.defn(name="finalize_signal_implementation_activity")
    async def finalize(input: SignalImplementationInput) -> list[FinalizedSignal]:
        return [
            FinalizedSignal(signal_id=signal_key, timestamp=datetime(2026, 1, 1, tzinfo=UTC))
            for signal_key in (input.signal_key, *input.additional_signal_keys)
        ]

    @activity.defn(name="wait_for_signal_in_clickhouse_activity")
    async def wait_for_clickhouse(input: WaitForClickHouseInput) -> None:
        wait_inputs.append(input)

    @activity.defn(name="release_signal_key_activity")
    async def release(input: SignalImplementationInput) -> None:
        return None

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="signal-implementation-batch-test",
            workflows=[SignalImplementationFinalizerWorkflow],
            activities=[finalize, wait_for_clickhouse, release],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                SignalImplementationFinalizerWorkflow.run,
                SignalImplementationInput(
                    team_id=1,
                    signal_key=signal_keys[0],
                    additional_signal_keys=tuple(signal_keys[1:]),
                ),
                id="signal-implementation-finalizer-batch-test",
                task_queue="signal-implementation-batch-test",
            )

    assert len(wait_inputs) == 1
    assert [signal.signal_id for signal in wait_inputs[0].signals] == signal_keys


@pytest.mark.asyncio
async def test_safety_rejection_marks_handoff_deleted_before_it_is_saved() -> None:
    handoff = SignalHandoff(
        team_id=1,
        signal=SignalData(
            signal_id="signal-id",
            content="content",
            source_product="signals",
            source_type="test",
            source_id="source-id",
            weight=1.0,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        embedding=[],
    )

    def async_boundary(fn, **_kwargs):
        async def call(*args, **kwargs):
            return fn(*args, **kwargs)

        return call

    with (
        patch("products.signals.backend.temporal.report_safety_judge.database_sync_to_async", async_boundary),
        patch(
            "products.signals.backend.temporal.report_safety_judge.judge_report_safety",
            AsyncMock(return_value=SafetyJudgeResponse(choice=False, explanation="injection")),
        ),
        patch("products.signals.backend.temporal.report_safety_judge.SignalReportArtefact.append_status"),
        patch("products.signals.backend.temporal.report_safety_judge.read_handoff", AsyncMock(return_value=handoff)),
        patch("products.signals.backend.temporal.report_safety_judge.write_handoff", AsyncMock()) as write_handoff,
    ):
        await report_safety_judge_activity(
            SafetyJudgeInput(team_id=1, report_id="report-id", signals=[], signal_key="handoff")
        )

    assert handoff.signal.metadata["deleted"] is True
    assert write_handoff.await_count == 1


@pytest.mark.asyncio
async def test_finalizer_rejects_a_missing_task_run() -> None:
    def async_boundary(fn, **_kwargs):
        async def call(*args, **kwargs):
            return fn(*args, **kwargs)

        return call

    with (
        patch("products.signals.backend.temporal.signal_implementation.database_sync_to_async", async_boundary),
        patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=None),
    ):
        with pytest.raises(ValueError, match="is missing"):
            await finalize_signal_implementation_activity(
                SignalImplementationInput(team_id=1, signal_key="handoff", task_id="task-id", run_id="run-id")
            )
