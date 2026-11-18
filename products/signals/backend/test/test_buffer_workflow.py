import uuid
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import TYPE_CHECKING

import pytest
from unittest.mock import patch

from temporalio import activity
from temporalio.client import WorkflowContinuedAsNewError
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.exceptions import QuotaLimitExceeded
from posthog.sync import database_sync_to_async

from products.signals.backend.daily_limit import DailyReportLimitGate
from products.signals.backend.spend import begin_signal_spend, finalized_signal_ids
from products.signals.backend.temporal.buffer import (
    BufferSignalsWorkflow,
    CheckSignalsQuotaInput,
    FlushBufferInput,
    FlushBufferOutput,
    SignalWithStartGroupingV2Input,
    check_signals_quota_limited_activity,
)
from products.signals.backend.temporal.safety_filter import (
    SafetyFilterInput,
    SafetyFilterOutput,
    safety_filter_activity,
)
from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs
from products.signals.backend.trial.policy import TrialRefused

if TYPE_CHECKING:
    from posthog.models import Team

TASK_QUEUE = "test-buffer-queue"
BUFFER_MODULE = "products.signals.backend.temporal.buffer"


def _signal(team_id: int) -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=team_id,
        source_product="error_tracking",
        source_type="issue",
        source_id=str(uuid.uuid4()),
        description="something happened",
    )


class _Recorder:
    def __init__(self, over_quota: bool, safety_failures: int = 0, mixed_batch: bool = False) -> None:
        self.over_quota = over_quota
        self.safety_failures = safety_failures
        self.mixed_batch = mixed_batch
        self.safety_sources: list[str | None] = []
        self.quota_checks = 0
        self.safety_checks = 0
        self.flushes = 0
        self.flushed_sources: list[str] = []
        self.grouping_starts = 0


async def _drive(recorder: _Recorder, pending_signals: list[EmitSignalInputs] | None = None) -> int:
    @activity.defn(name="check_signals_quota_limited_activity")
    async def fake_quota(_input: CheckSignalsQuotaInput) -> bool:
        recorder.quota_checks += 1
        return recorder.over_quota

    @activity.defn(name="safety_filter_activity")
    async def fake_safety(_input: SafetyFilterInput) -> SafetyFilterOutput:
        recorder.safety_checks += 1
        recorder.safety_sources.append(_input.source_id)
        if _input.source_id == "refused":
            return await safety_filter_activity(_input)
        if _input.source_id == "unsafe":
            return SafetyFilterOutput(safe=False, threat_type="test", explanation=None)
        if recorder.safety_failures > 0:
            recorder.safety_failures -= 1
            raise ApplicationError("safety provider unavailable", non_retryable=True)
        return SafetyFilterOutput(safe=True, threat_type="", explanation=None)

    @activity.defn(name="flush_signals_to_s3_activity")
    async def fake_flush(input: FlushBufferInput) -> FlushBufferOutput:
        recorder.flushes += 1
        recorder.flushed_sources.extend(signal.source_id for signal in input.signals)
        return FlushBufferOutput(object_key="signals/batch/test", signal_count=len(input.signals))

    @activity.defn(name="signal_with_start_grouping_v2_activity")
    async def fake_grouping(_input: SignalWithStartGroupingV2Input) -> None:
        recorder.grouping_starts += 1

    return await _run_buffer_workflow(recorder, [fake_quota, fake_safety, fake_flush, fake_grouping], pending_signals)


async def _run_buffer_workflow(
    recorder: _Recorder,
    activities: list[Callable[..., Awaitable[object]]],
    pending_signals: list[EmitSignalInputs] | None = None,
) -> int:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BufferSignalsWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            signals = list(pending_signals or [])
            if pending_signals is None and recorder.mixed_batch:
                unsafe = _signal(1)
                unsafe.source_id = "unsafe"
                signals = [unsafe, _signal(1)]
            handle = await env.client.start_workflow(
                BufferSignalsWorkflow.run,
                BufferSignalsInput(
                    team_id=pending_signals[0].team_id if pending_signals else 1,
                    pending_signals=signals,
                ),
                id=f"buffer-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            if pending_signals is None and not recorder.mixed_batch:
                await handle.signal(BufferSignalsWorkflow.submit_signal, _signal(1))
            try:
                run_id = handle.first_execution_run_id
                async with asyncio.timeout(30):
                    while True:
                        completed = env.client.get_workflow_handle(handle.id, run_id=run_id)
                        with pytest.raises(WorkflowContinuedAsNewError):
                            await completed.result(follow_runs=False)
                        history = await completed.fetch_history()
                        continued = history.events[-1].workflow_execution_continued_as_new_event_attributes
                        [next_input] = await env.client.data_converter.decode(
                            continued.input.payloads, [BufferSignalsInput]
                        )
                        if recorder.over_quota or recorder.grouping_starts:
                            return len(next_input.pending_signals)
                        run_id = continued.new_execution_run_id
            finally:
                with suppress(RPCError):
                    await env.client.get_workflow_handle(handle.id).terminate()


@pytest.mark.asyncio
async def test_recorded_limit_rejection_drops_batch():
    recorder = _Recorder(over_quota=True)
    await _drive(recorder)
    assert recorder.quota_checks >= 1
    # The batch is dropped at the gate, so nothing downstream runs.
    assert recorder.safety_checks == 0
    assert recorder.flushes == 0
    assert recorder.grouping_starts == 0


@pytest.mark.asyncio
async def test_under_quota_batch_flows_through():
    recorder = _Recorder(over_quota=False)
    await _drive(recorder)
    assert recorder.quota_checks >= 1
    assert recorder.safety_checks == 1
    assert recorder.flushes == 1
    assert recorder.grouping_starts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed_batch", [False, True])
async def test_safety_failure_requeues_only_failed_signals(mixed_batch: bool):
    recorder = _Recorder(over_quota=False, safety_failures=1, mixed_batch=mixed_batch)
    await _drive(recorder)
    assert recorder.safety_checks == 2 + int(mixed_batch)
    assert recorder.safety_sources.count("unsafe") == int(mixed_batch)
    assert recorder.flushes == 1
    assert recorder.grouping_starts == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("refusal", [QuotaLimitExceeded(), TrialRefused("trial_expired")])
async def test_safety_admission_refusal_drops_signal_without_requeueing(ateam: "Team", refusal: Exception) -> None:
    refused = _signal(ateam.id)
    refused.source_id = "refused"
    refused.signal_id = str(uuid.uuid4())
    healthy = _signal(ateam.id)
    await database_sync_to_async(begin_signal_spend)(team_id=ateam.id, signal_id=refused.signal_id)
    recorder = _Recorder(over_quota=False)

    with (
        patch("products.signals.backend.temporal.safety_filter.call_llm", side_effect=refusal),
        patch("posthoganalytics.get_feature_flag", return_value=None),
        patch("posthoganalytics.capture_exception") as capture_exception,
        patch("posthoganalytics.capture") as capture,
    ):
        remaining = await _drive(recorder, pending_signals=[refused, healthy])

    assert await database_sync_to_async(finalized_signal_ids)(team_id=ateam.id, signal_ids=[refused.signal_id]) == {
        refused.signal_id
    }
    assert remaining == 0
    assert recorder.safety_checks == 2
    assert recorder.flushed_sources == [healthy.source_id]
    assert recorder.grouping_starts == 1
    capture_exception.assert_not_called()
    assert "signal_blocked_by_safety_filter" not in [call.kwargs.get("event") for call in capture.call_args_list]


# ---------------------------------------------------------------------------
# check_signals_quota_limited_activity: compatibility for recorded workflow commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("billing_limited,daily_limited", [(True, False), (False, True), (True, True), (False, False)])
async def test_buffer_does_not_recheck_limits(billing_limited, daily_limited):
    with (
        patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=billing_limited) as billing,
        patch(
            "products.signals.backend.daily_limit.daily_report_limit_gate",
            return_value=DailyReportLimitGate(limited=daily_limited, limit=2, reports_today=2),
        ) as daily,
        patch(f"{BUFFER_MODULE}.metrics.increment_dropped") as dropped,
    ):
        result = await ActivityEnvironment().run(
            check_signals_quota_limited_activity,
            CheckSignalsQuotaInput(team_id=1, signal_count=1, signals=[_signal(1)]),
        )
    assert result is False
    billing.assert_not_called()
    daily.assert_not_called()
    dropped.assert_not_called()
