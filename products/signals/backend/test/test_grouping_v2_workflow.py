import uuid
import asyncio
from datetime import timedelta

import pytest
from unittest.mock import patch

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.temporal.drop_telemetry import CaptureSignalDroppedInput
from products.signals.backend.temporal.grouping_v2 import MAX_BATCH_ATTEMPTS, TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.signal_queries import FetchSignalTypeExamplesInput
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ReadSignalsFromS3Input,
    ReadSignalsFromS3Output,
    TeamSignalGroupingV2Input,
)

TASK_QUEUE = "test-grouping-v2-queue"
GROUPING_V2_MODULE = "products.signals.backend.temporal.grouping_v2"


class _Recorder:
    def __init__(self) -> None:
        self.reads = 0
        self.drops = 0
        self.dropped = asyncio.Event()


@pytest.mark.asyncio
async def test_poison_batch_is_dead_lettered_after_attempt_cap():
    # A batch whose preparation always fails must not retry forever: it is retried up to the cap,
    # then dead-lettered so the buffer drains, and its one signal drops exactly once — not once per
    # attempt, which is what jammed a team's pipeline and inflated the signal_dropped metric.
    recorder = _Recorder()
    signal = EmitSignalInputs(
        team_id=1,
        source_product="error_tracking",
        source_type="issue",
        source_id=str(uuid.uuid4()),
        description="poison signal",
    )

    @activity.defn(name="read_signals_from_s3_activity")
    async def fake_read(_input: ReadSignalsFromS3Input) -> ReadSignalsFromS3Output:
        recorder.reads += 1
        return ReadSignalsFromS3Output(signals=[signal])

    @activity.defn(name="fetch_signal_type_examples_activity")
    async def fake_prep_fails(_input: FetchSignalTypeExamplesInput) -> None:
        raise ApplicationError("embedding API 500", non_retryable=True)

    @activity.defn(name="capture_signal_dropped_activity")
    async def fake_drop(_input: CaptureSignalDroppedInput) -> None:
        recorder.drops += 1
        recorder.dropped.set()

    # Shrink the collection window and retry backoff so the retry loop runs in milliseconds instead
    # of the ~44s-per-round wall clock it takes in production.
    with (
        patch(f"{GROUPING_V2_MODULE}.BATCH_COLLECT_TIMEOUT", timedelta(seconds=1)),
        patch(f"{GROUPING_V2_MODULE}.RETRY_BACKOFF", timedelta(seconds=0)),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[TeamSignalGroupingV2Workflow],
                activities=[fake_read, fake_prep_fails, fake_drop],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    TeamSignalGroupingV2Workflow.run,
                    TeamSignalGroupingV2Input(team_id=1),
                    id=f"grouping-v2-{uuid.uuid4()}",
                    task_queue=TASK_QUEUE,
                )
                await handle.signal(TeamSignalGroupingV2Workflow.submit_batch, "signals/batch/poison")
                await asyncio.wait_for(recorder.dropped.wait(), timeout=30)
                await env.client.get_workflow_handle(handle.id).terminate()

    # Read once per attempt: the key is re-collected each round until the cap dead-letters it.
    assert recorder.reads == MAX_BATCH_ATTEMPTS
    # Emitted once for the signal, not once per attempt.
    assert recorder.drops == 1
