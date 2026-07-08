import uuid
import asyncio

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.temporal.buffer import (
    BufferSignalsWorkflow,
    CheckSignalsQuotaInput,
    FlushBufferInput,
    FlushBufferOutput,
    SignalWithStartGroupingV2Input,
)
from products.signals.backend.temporal.safety_filter import SafetyFilterInput, SafetyFilterOutput
from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs

TASK_QUEUE = "test-buffer-queue"


def _signal(team_id: int) -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=team_id,
        source_product="error_tracking",
        source_type="issue",
        source_id=str(uuid.uuid4()),
        description="something happened",
    )


class _Recorder:
    def __init__(self, over_quota: bool) -> None:
        self.over_quota = over_quota
        self.quota_checks = 0
        self.safety_checks = 0
        self.flushes = 0
        self.grouping_starts = 0
        # The drop path ends at the quota check; the pass-through path ends at grouping. Each path's
        # terminal activity sets its event so the test knows the batch finished processing.
        self.gate_reached = asyncio.Event()
        self.flow_done = asyncio.Event()


async def _drive(recorder: _Recorder) -> None:
    @activity.defn(name="check_signals_quota_limited_activity")
    async def fake_quota(_input: CheckSignalsQuotaInput) -> bool:
        recorder.quota_checks += 1
        recorder.gate_reached.set()
        return recorder.over_quota

    @activity.defn(name="safety_filter_activity")
    async def fake_safety(_input: SafetyFilterInput) -> SafetyFilterOutput:
        recorder.safety_checks += 1
        return SafetyFilterOutput(safe=True, threat_type="", explanation=None)

    @activity.defn(name="flush_signals_to_s3_activity")
    async def fake_flush(input: FlushBufferInput) -> FlushBufferOutput:
        recorder.flushes += 1
        return FlushBufferOutput(object_key="signals/batch/test", signal_count=len(input.signals))

    @activity.defn(name="signal_with_start_grouping_v2_activity")
    async def fake_grouping(_input: SignalWithStartGroupingV2Input) -> None:
        recorder.grouping_starts += 1
        recorder.flow_done.set()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[BufferSignalsWorkflow],
            activities=[fake_quota, fake_safety, fake_flush, fake_grouping],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                BufferSignalsWorkflow.run,
                BufferSignalsInput(team_id=1),
                id=f"buffer-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            await handle.signal(BufferSignalsWorkflow.submit_signal, _signal(1))
            terminal = recorder.gate_reached if recorder.over_quota else recorder.flow_done
            await asyncio.wait_for(terminal.wait(), timeout=30)
            await handle.terminate()


@pytest.mark.asyncio
async def test_over_quota_batch_is_dropped():
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
