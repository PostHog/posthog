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
    # A source match skips the type-example and query-generation steps, so the embedding is the first batch activity.
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
@pytest.mark.parametrize("ai_approved", [True, False])
@pytest.mark.parametrize(
    "pending_keys,failed_rounds_by_batch_key,failed_consent_attempts",
    [
        (["batch-a"], {}, 0),
        (["batch-a", "batch-b"], {"batch-a": 2}, 3),
    ],
)
async def test_failed_batch_retries_report_each_attempt(
    pending_keys: list[str], failed_rounds_by_batch_key: dict[str, int], failed_consent_attempts: int, ai_approved: bool
) -> None:
    expected_drops = sorted(
        (signal.source_id, failed_rounds_by_batch_key.get(key, 0) + round_index + 1)
        for round_index in range(ROUNDS)
        for key in pending_keys
        for signal in BATCHES[key]
    )
    last_attempt = dict(expected_drops)
    drops: list[tuple[str, int | None]] = []
    read_keys: list[str] = []
    discarded_keys: list[str] = []
    rounds_done = asyncio.Event()

    @activity.defn(name="check_signals_ai_consent_activity")
    async def fake_consent(_team_id: int) -> bool:
        if activity.info().attempt <= failed_consent_attempts:
            raise ApplicationError("Consent database unavailable")
        return ai_approved

    @activity.defn(name="discard_signal_batches_activity")
    async def fake_discard(object_keys: list[str]) -> None:
        discarded_keys.extend(object_keys)

    @activity.defn(name="read_signals_from_s3_activity")
    async def fake_read(input: ReadSignalsFromS3Input) -> ReadSignalsFromS3Output:
        read_keys.append(input.object_key)
        return ReadSignalsFromS3Output(signals=BATCHES[input.object_key])

    @activity.defn(name="get_embedding_activity")
    async def fake_embedding(_input: GenerateEmbeddingInput) -> GenerateEmbeddingOutput:
        raise ApplicationError("Embedding worker returned 403", type="HTTPStatusError", non_retryable=True)

    @activity.defn(name="capture_signal_dropped_activity")
    async def fake_capture(input: CaptureSignalDroppedInput) -> None:
        drops.append((input.source_id, input.attempt))
        if len(drops) >= len(expected_drops):
            rounds_done.set()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[TeamSignalGroupingV2Workflow],
            activities=[fake_consent, fake_discard, fake_read, fake_embedding, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                TeamSignalGroupingV2Workflow.run,
                TeamSignalGroupingV2Input(
                    team_id=1,
                    pending_batch_keys=pending_keys,
                    failed_rounds_by_batch_key=failed_rounds_by_batch_key,
                ),
                id=f"grouping-v2-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
                execution_timeout=timedelta(minutes=15),
            )
            if not ai_approved:
                await asyncio.wait_for(handle.result(), timeout=10)
                assert read_keys == []
                assert discarded_keys == pending_keys
                assert drops == []
                return

            # The time-skipping server only skips time while the client waits on it, so step the clock
            # past the retry backoff and the batch-collection timeout until the rounds finish.
            for _ in range(60):
                if rounds_done.is_set():
                    break
                await env.sleep(timedelta(seconds=10))
            assert rounds_done.is_set()
            with suppress(RPCError):
                await env.client.get_workflow_handle(handle.id).terminate()

    # The workflow keeps retrying until it is terminated, so ignore any round that started after the last checked one.
    assert sorted(drop for drop in drops if drop[1] is None or drop[1] <= last_attempt[drop[0]]) == expected_drops
    assert discarded_keys == []
