from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.signal_costs import add_cost
from products.signals.backend.signal_handoffs import SignalHandoff
from products.signals.backend.temporal.report_safety_judge import (
    SafetyJudgeInput,
    SafetyJudgeResponse,
    report_safety_judge_activity,
)
from products.signals.backend.temporal.signal_implementation import (
    SignalImplementationFinalizerWorkflow,
    SignalImplementationInput,
    finalize_signal_implementation_activity,
)
from products.signals.backend.temporal.types import SignalData


@pytest.mark.asyncio
async def test_finalizer_charges_a_task_once_when_the_finish_activity_retries() -> None:
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
    )
    workflow_handle = MagicMock(
        describe=AsyncMock(
            side_effect=[
                SimpleNamespace(status=status)
                for status in (
                    WorkflowExecutionStatus.RUNNING,
                    WorkflowExecutionStatus.COMPLETED,
                    WorkflowExecutionStatus.COMPLETED,
                )
            ]
        )
    )
    client = MagicMock(get_workflow_handle=MagicMock(return_value=workflow_handle))
    run = SimpleNamespace(workflow_id="task-workflow", task_id="task-id")
    spend = SimpleNamespace(token_cost=10, compute_cost=20)

    with (
        patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=run),
        patch("products.signals.backend.temporal.signal_implementation.async_connect", AsyncMock(return_value=client)),
        patch("products.signals.backend.signal_handoffs.get_task_spend", return_value=spend),
        patch("products.signals.backend.signal_handoffs.read_handoff", AsyncMock(return_value=handoff)),
        patch("products.signals.backend.signal_handoffs.write_handoff", AsyncMock()) as write_handoff,
        patch(
            "products.signals.backend.temporal.signal_implementation.publish_handoff", AsyncMock()
        ) as publish_handoff,
    ):
        input = SignalImplementationInput(team_id=1, signal_keys=("handoff",), run_id="run-id")
        assert not await finalize_signal_implementation_activity(input)
        publish_handoff.assert_not_awaited()
        assert handoff.costed_tasks == []
        assert await finalize_signal_implementation_activity(input)
        assert await finalize_signal_implementation_activity(input)

    assert workflow_handle.describe.await_count == 3
    assert handoff.costed_tasks == ["task-id"]
    assert handoff.signal.metadata["token_cost"]["implementation"] == 10
    assert handoff.signal.metadata["compute_cost"]["implementation"] == 20
    write_handoff.assert_awaited_once()
    assert publish_handoff.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("is_terminal,finalized", [(False, False), (True, True)])
async def test_a_task_workflow_temporal_has_not_started_yet_waits_for_its_run(
    is_terminal: bool, finalized: bool
) -> None:
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
    )
    workflow_handle = MagicMock(
        describe=AsyncMock(side_effect=RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b""))
    )
    client = MagicMock(get_workflow_handle=MagicMock(return_value=workflow_handle))
    run = SimpleNamespace(workflow_id="task-workflow", task_id="task-id", is_terminal=is_terminal)

    with (
        patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=run),
        patch("products.signals.backend.temporal.signal_implementation.async_connect", AsyncMock(return_value=client)),
        patch(
            "products.signals.backend.signal_handoffs.get_task_spend",
            return_value=SimpleNamespace(token_cost=0, compute_cost=0),
        ),
        patch("products.signals.backend.signal_handoffs.read_handoff", AsyncMock(return_value=handoff)),
        patch("products.signals.backend.signal_handoffs.write_handoff", AsyncMock()),
        patch(
            "products.signals.backend.temporal.signal_implementation.publish_handoff", AsyncMock()
        ) as publish_handoff,
    ):
        result = await finalize_signal_implementation_activity(
            SignalImplementationInput(team_id=1, signal_keys=("handoff",), run_id="run-id")
        )

    assert result is finalized
    assert publish_handoff.await_count == (1 if finalized else 0)


@pytest.mark.asyncio
async def test_a_describe_failure_that_is_not_a_missing_workflow_still_raises() -> None:
    workflow_handle = MagicMock(describe=AsyncMock(side_effect=RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")))
    client = MagicMock(get_workflow_handle=MagicMock(return_value=workflow_handle))
    run = SimpleNamespace(workflow_id="task-workflow", task_id="task-id", is_terminal=False)

    with (
        patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=run),
        patch("products.signals.backend.temporal.signal_implementation.async_connect", AsyncMock(return_value=client)),
    ):
        with pytest.raises(RPCError):
            await finalize_signal_implementation_activity(
                SignalImplementationInput(team_id=1, signal_keys=("handoff",), run_id="run-id")
            )


@pytest.mark.asyncio
async def test_one_unpublishable_key_does_not_hold_back_its_batch() -> None:
    keys = tuple(f"signal-{i}" for i in range(5))

    async def publish(signal_key: str, team_id: int) -> None:
        if signal_key == "signal-2":
            raise ValueError("Signal handoff is missing")

    with patch(
        "products.signals.backend.temporal.signal_implementation.publish_handoff", AsyncMock(side_effect=publish)
    ) as publish_handoff:
        with pytest.raises(RuntimeError, match="signal-2"):
            await finalize_signal_implementation_activity(SignalImplementationInput(team_id=1, signal_keys=keys))

    assert [call.args[0] for call in publish_handoff.await_args_list] == list(keys)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keys,run_id,answers",
    [(("owner",), "run-id", (False, True)), (tuple(f"signal-{i}" for i in range(20)), None, (True,))],
)
async def test_finalizer_polls_with_a_timer_or_publishes_a_batch(
    keys: tuple[str, ...], run_id: str | None, answers: tuple[bool, ...]
) -> None:
    input = SignalImplementationInput(team_id=1, signal_keys=keys, run_id=run_id)
    calls: list[SignalImplementationInput] = []
    results = iter(answers)

    @activity.defn(name="finalize_signal_implementation_activity")
    async def finalize(input: SignalImplementationInput) -> bool:
        calls.append(input)
        return next(results)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="signal-implementation-test",
            workflows=[SignalImplementationFinalizerWorkflow],
            activities=[finalize],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                SignalImplementationFinalizerWorkflow.run,
                input,
                id="signal-implementation-finalizer-test",
                task_queue="signal-implementation-test",
            )
            history = await env.client.get_workflow_handle("signal-implementation-finalizer-test").fetch_history()

    assert calls == [input] * len(answers)
    assert [
        event.timer_started_event_attributes.start_to_fire_timeout.seconds
        for event in history.events
        if event.HasField("timer_started_event_attributes")
    ] == [60] * (len(answers) - 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("safe", [False, True])
@pytest.mark.parametrize("persist_failure", [False, True])
async def test_safety_result_preserves_verdict_but_discards_failed_attempt_costs(
    safe: bool, persist_failure: bool
) -> None:
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
    )

    add_cost(handoff.signal.metadata, "grouping-model", token_cost=3)

    async def judge(*, team_id: int, signals: list[SignalData], costs: dict) -> SafetyJudgeResponse:
        add_cost(costs, "safety-model", token_cost=5)
        return SafetyJudgeResponse(choice=safe, explanation="assessment")

    with (
        patch("products.signals.backend.temporal.report_safety_judge.judge_report_safety", side_effect=judge),
        patch(
            "products.signals.backend.temporal.report_safety_judge.SignalReportArtefact.append_status",
            side_effect=RuntimeError("artifact write failed") if persist_failure else None,
        ),
        patch("products.signals.backend.temporal.report_safety_judge.read_handoff", AsyncMock(return_value=handoff)),
        patch("products.signals.backend.temporal.report_safety_judge.write_handoff", AsyncMock()) as write_handoff,
        pytest.raises(RuntimeError, match="artifact write failed") if persist_failure else nullcontext(),
    ):
        await report_safety_judge_activity(
            SafetyJudgeInput(team_id=1, report_id="report-id", signals=[], signal_key="handoff")
        )

    assert handoff.signal.metadata.get("deleted", False) is (not safe)
    assert handoff.signal.metadata["token_cost"] == {"research": 3 if persist_failure else 8, "implementation": 0}
    write_handoff.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalizer_rejects_a_missing_task_run() -> None:
    with patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=None):
        with pytest.raises(ValueError, match="is missing"):
            await finalize_signal_implementation_activity(
                SignalImplementationInput(team_id=1, signal_keys=("handoff",), run_id="run-id")
            )
