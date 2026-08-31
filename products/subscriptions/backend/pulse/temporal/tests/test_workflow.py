import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from products.subscriptions.backend.pulse.temporal.inputs import (
    ProactiveDispatchSnapshot,
    PulseWorkflowInput,
    PulseWorkflowResult,
)
from products.subscriptions.backend.temporal import pulse as pulse_workflow_module
from products.subscriptions.backend.temporal.pulse import PulseWorkflow


def _input(*, deadline: datetime | None = None) -> PulseWorkflowInput:
    return PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=uuid4(),
        pulse_run_id=uuid4(),
        report_snapshot_ref="subscription-delivery:1",
        deadline=deadline or datetime(2026, 8, 29, 12, 10, tzinfo=UTC),
        proactive_snapshot=ProactiveDispatchSnapshot(
            version=1,
            enabled=True,
            config_snapshot_ref="pulse-config:1",
            wall_clock_budget_seconds=600,
            finalization_margin_seconds=60,
        ),
    )


@pytest.mark.asyncio
async def test_returns_durable_terminal_result_from_pulse_step(monkeypatch) -> None:
    input = _input()
    expected = PulseWorkflowResult(
        pulse_run_id=input.pulse_run_id,
        status="completed",
        result_ref="pulse-result:1",
    )
    execute_activity = AsyncMock(return_value=expected)
    monkeypatch.setattr(pulse_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(pulse_workflow_module.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC))

    result = await PulseWorkflow().run(input)

    assert result == expected
    execute_activity.assert_awaited_once_with(
        pulse_workflow_module.advance_pulse_workflow,
        input,
        start_to_close_timeout=timedelta(minutes=2),
        schedule_to_close_timeout=timedelta(minutes=2),
        retry_policy=pulse_workflow_module.PULSE_ACTIVITY_RETRY_POLICY,
    )


@pytest.mark.asyncio
async def test_advance_activity_is_bounded_by_the_remaining_finalization_window(monkeypatch) -> None:
    input = _input()
    expected = PulseWorkflowResult(
        pulse_run_id=input.pulse_run_id,
        status="completed",
        result_ref="pulse-result:1",
    )
    execute_activity = AsyncMock(return_value=expected)
    monkeypatch.setattr(pulse_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(
        pulse_workflow_module.workflow,
        "now",
        lambda: datetime(2026, 8, 29, 12, 8, 30, tzinfo=UTC),
    )

    assert await PulseWorkflow().run(input) == expected
    execute_activity.assert_awaited_once_with(
        pulse_workflow_module.advance_pulse_workflow,
        input,
        start_to_close_timeout=timedelta(seconds=30),
        schedule_to_close_timeout=timedelta(seconds=30),
        retry_policy=pulse_workflow_module.PULSE_ACTIVITY_RETRY_POLICY,
    )


@pytest.mark.asyncio
async def test_deadline_finalizes_without_another_pulse_step(monkeypatch) -> None:
    input = _input(deadline=datetime(2026, 8, 29, 12, tzinfo=UTC))
    expected = PulseWorkflowResult(
        pulse_run_id=input.pulse_run_id,
        status="partial",
        result_ref="pulse-result:timeout",
        failure_code="pulse_timed_out",
    )
    execute_activity = AsyncMock(return_value=expected)
    monkeypatch.setattr(pulse_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(pulse_workflow_module.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC))

    result = await PulseWorkflow().run(input)

    assert result == expected
    execute_activity.assert_awaited_once_with(
        pulse_workflow_module.finalize_timed_out_pulse_workflow,
        input,
        start_to_close_timeout=timedelta(seconds=1),
        schedule_to_close_timeout=timedelta(seconds=1),
        retry_policy=pulse_workflow_module.PULSE_ACTIVITY_RETRY_POLICY,
    )


@pytest.mark.asyncio
async def test_reserved_margin_starts_finalization_before_the_hard_deadline(monkeypatch) -> None:
    input = _input(deadline=datetime(2026, 8, 29, 12, 10, tzinfo=UTC))
    expected = PulseWorkflowResult(
        pulse_run_id=input.pulse_run_id,
        status="partial",
        result_ref="pulse-result:cutoff",
        failure_code="finalization_timeout",
    )
    execute_activity = AsyncMock(return_value=expected)
    monkeypatch.setattr(pulse_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(pulse_workflow_module.workflow, "now", lambda: datetime(2026, 8, 29, 12, 9, tzinfo=UTC))

    result = await PulseWorkflow().run(input)

    assert result == expected
    execute_activity.assert_awaited_once_with(
        pulse_workflow_module.finalize_timed_out_pulse_workflow,
        input,
        start_to_close_timeout=timedelta(minutes=1),
        schedule_to_close_timeout=timedelta(minutes=1),
        retry_policy=pulse_workflow_module.PULSE_ACTIVITY_RETRY_POLICY,
    )


@pytest.mark.asyncio
async def test_cancellation_records_cleanup_before_reraising(monkeypatch) -> None:
    input = _input()
    execute_activity = AsyncMock(
        side_effect=[
            asyncio.CancelledError(),
            PulseWorkflowResult(
                pulse_run_id=input.pulse_run_id,
                status="cancelled",
                result_ref="pulse-result:cancelled",
            ),
        ]
    )
    monkeypatch.setattr(pulse_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(pulse_workflow_module.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC))

    with pytest.raises(asyncio.CancelledError):
        await PulseWorkflow().run(input)

    assert execute_activity.await_args_list[1].args == (pulse_workflow_module.cancel_pulse_workflow, input)
