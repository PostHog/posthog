import uuid

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.temporal.buffer import SubmitSignalToBufferInput
from products.signals.backend.temporal.drop_telemetry import CaptureSignalDroppedInput
from products.signals.backend.temporal.emitter import EMITTER_RUN_TIMEOUT, SignalEmitterInput, SignalEmitterWorkflow
from products.signals.backend.temporal.types import EmitSignalInputs

TASK_QUEUE = "test-emitter-queue"


@pytest.mark.asyncio
async def test_emitter_records_drop_when_submit_to_buffer_fails():
    drops: list[CaptureSignalDroppedInput] = []

    @activity.defn(name="submit_signal_to_buffer_activity")
    async def fake_submit(_input: SubmitSignalToBufferInput) -> None:
        raise ApplicationError("buffer workflow not found", non_retryable=True)

    @activity.defn(name="capture_signal_dropped_activity")
    async def fake_capture(input: CaptureSignalDroppedInput) -> None:
        drops.append(input)

    signal = EmitSignalInputs(
        team_id=1,
        source_product="linear",
        source_type="issue",
        source_id="issue-1",
        description="something happened",
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[SignalEmitterWorkflow],
            activities=[fake_submit, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    SignalEmitterWorkflow.run,
                    SignalEmitterInput(team_id=1, signal=signal),
                    id=f"signal-emitter-test-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                    run_timeout=EMITTER_RUN_TIMEOUT,
                )

    assert len(drops) == 1
    assert drops[0].stage == "emission"
    assert drops[0].error_type == "ApplicationError"
    assert drops[0].source_id == "issue-1"
