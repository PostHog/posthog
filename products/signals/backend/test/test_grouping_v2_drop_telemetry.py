import uuid
import asyncio
from contextlib import suppress
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.temporal.drop_telemetry import CaptureSignalDroppedInput
from products.signals.backend.temporal.grouping import GenerateEmbeddingInput, GenerateEmbeddingOutput
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ReadSignalsFromS3Input,
    ReadSignalsFromS3Output,
    TeamSignalGroupingV2Input,
)

TASK_QUEUE = "test-grouping-v2-queue"
ROUNDS = 3


def _signal(source_id: str) -> EmitSignalInputs:
    # A source match skips the type-example and query-generation steps, so the embedding is the first activity.
    return EmitSignalInputs(
        team_id=1,
        source_product="error_tracking",
        source_type="issue_created",
        source_id=source_id,
        description="something happened",
        source_match_signal_id="previous-signal",
        source_match_report_id="existing-report",
    )


BATCHES = {
    "batch-a": [_signal("a-1"), _signal("a-2")],
    "batch-b": [_signal("b-1")],
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending_keys,retried_keys,expected_drops",
    [
        (["batch-a"], [], ["a-1", "a-2"]),
        (["batch-a", "batch-b"], ["batch-a"], ["b-1"]),
    ],
)
async def test_failed_batch_retries_report_one_drop_per_signal(
    pending_keys: list[str], retried_keys: list[str], expected_drops: list[str]
) -> None:
    drops: list[str] = []
    embedding_calls = 0
    signal_count = sum(len(BATCHES[key]) for key in pending_keys)
    rounds_done = asyncio.Event()

    @activity.defn(name="read_signals_from_s3_activity")
    async def fake_read(input: ReadSignalsFromS3Input) -> ReadSignalsFromS3Output:
        return ReadSignalsFromS3Output(signals=BATCHES[input.object_key])

    @activity.defn(name="get_embedding_activity")
    async def fake_embedding(_input: GenerateEmbeddingInput) -> GenerateEmbeddingOutput:
        nonlocal embedding_calls
        embedding_calls += 1
        if embedding_calls >= ROUNDS * signal_count:
            rounds_done.set()
        raise ApplicationError("Embedding worker returned 403", type="HTTPStatusError", non_retryable=True)

    @activity.defn(name="capture_signal_dropped_activity")
    async def fake_capture(input: CaptureSignalDroppedInput) -> None:
        drops.append(input.source_id)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[TeamSignalGroupingV2Workflow],
            activities=[fake_read, fake_embedding, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                TeamSignalGroupingV2Workflow.run,
                TeamSignalGroupingV2Input(team_id=1, pending_batch_keys=pending_keys, retried_batch_keys=retried_keys),
                id=f"grouping-v2-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            # The time-skipping server only skips time while the client waits on it, so step the clock
            # past the retry backoff and the batch-collection timeout until the rounds finish.
            for _ in range(60):
                if rounds_done.is_set():
                    break
                await env.sleep(timedelta(seconds=10))
            assert rounds_done.is_set()
            with suppress(RPCError):
                await env.client.get_workflow_handle(handle.id).terminate()

    assert sorted(drops) == expected_drops
