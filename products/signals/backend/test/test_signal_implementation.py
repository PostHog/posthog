from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.signals.backend.signal_handoffs import SignalHandoff
from products.signals.backend.temporal.report_safety_judge import (
    SafetyJudgeInput,
    SafetyJudgeResponse,
    report_safety_judge_activity,
)
from products.signals.backend.temporal.signal_implementation import (
    SignalImplementationInput,
    finalize_signal_implementation_activity,
)
from products.signals.backend.temporal.types import SignalData


@pytest.mark.asyncio
async def test_finalizer_waits_for_task_workflow_and_costs_once() -> None:
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
    workflow_handle = MagicMock(result=AsyncMock())
    client = MagicMock(get_workflow_handle=MagicMock(return_value=workflow_handle))
    run = SimpleNamespace(workflow_id="task-workflow", task_id="task-id")
    spend = SimpleNamespace(token_cost=10, compute_cost=20)
    heartbeat = MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())

    def async_boundary(fn, **_kwargs):
        async def call(*args, **kwargs):
            return fn(*args, **kwargs)

        return call

    with (
        patch("products.signals.backend.temporal.signal_implementation.database_sync_to_async", async_boundary),
        patch("products.signals.backend.temporal.signal_implementation.Heartbeater", return_value=heartbeat),
        patch("products.signals.backend.temporal.signal_implementation.tasks_facade.get_task_run", return_value=run),
        patch("products.signals.backend.temporal.signal_implementation.get_task_spend", return_value=spend),
        patch("products.signals.backend.temporal.signal_implementation.async_connect", AsyncMock(return_value=client)),
        patch("products.signals.backend.temporal.signal_implementation.read_handoff", AsyncMock(return_value=handoff)),
        patch("products.signals.backend.temporal.signal_implementation.write_handoff", AsyncMock()) as write_handoff,
        patch("products.signals.backend.temporal.signal_implementation.publish_handoff", AsyncMock()),
    ):
        input = SignalImplementationInput(team_id=1, signal_key="handoff", task_id="task-id", run_id="run-id")
        await finalize_signal_implementation_activity(input)
        await finalize_signal_implementation_activity(input)

    workflow_handle.result.assert_awaited()
    assert handoff.costed_tasks == ["task-id"]
    assert handoff.signal.metadata["token_cost"]["implementation"] == 10
    assert handoff.signal.metadata["compute_cost"]["implementation"] == 20
    assert write_handoff.await_count == 2


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
