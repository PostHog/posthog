import uuid
import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.temporal.drop_telemetry import CaptureSignalDroppedInput
from products.signals.backend.temporal.grouping import (
    FetchSignalTypeExamplesInput,
    FetchSignalTypeExamplesOutput,
    GenerateEmbeddingInput,
    GenerateEmbeddingOutput,
    GenerateSearchQueriesInput,
    GenerateSearchQueriesOutput,
    SignalGroupingCompletion,
)
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ReadSignalsFromS3Input,
    ReadSignalsFromS3Output,
    TeamSignalGroupingV2Input,
)

TASK_QUEUE = "test-grouping-v2-queue"
FIRST_BATCH_KEY = "signals/batch/first"
SECOND_BATCH_KEY = "signals/batch/second"


class _Recorder:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.drops: list[CaptureSignalDroppedInput] = []
        self.completions: list[list[SignalGroupingCompletion]] = []


async def _wait_until(predicate: Callable[[], bool], timeout: float = 30.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


async def _drive(recorder: _Recorder, embedding_error: Callable[[], BaseException], rounds_of_first_batch: int) -> None:
    signal = EmitSignalInputs(
        team_id=1,
        source_product="error_tracking",
        source_type="issue",
        source_id="issue-1",
        description="Checkout crashes",
        signal_id="signal-1",
    )

    @activity.defn(name="read_signals_from_s3_activity")
    async def fake_read(input: ReadSignalsFromS3Input) -> ReadSignalsFromS3Output:
        recorder.reads.append(input.object_key)
        return ReadSignalsFromS3Output(signals=[signal])

    @activity.defn(name="fetch_signal_type_examples_activity")
    async def fake_type_examples(_input: FetchSignalTypeExamplesInput) -> FetchSignalTypeExamplesOutput:
        return FetchSignalTypeExamplesOutput(examples=[])

    @activity.defn(name="get_embedding_activity")
    async def fake_embedding(_input: GenerateEmbeddingInput) -> GenerateEmbeddingOutput:
        raise embedding_error()

    @activity.defn(name="generate_search_queries_activity")
    async def fake_queries(_input: GenerateSearchQueriesInput) -> GenerateSearchQueriesOutput:
        return GenerateSearchQueriesOutput(queries=["checkout crash"])

    @activity.defn(name="capture_signal_dropped_activity")
    async def fake_drop(input: CaptureSignalDroppedInput) -> None:
        recorder.drops.append(input)

    @activity.defn(name="complete_signal_grouping_activity")
    async def fake_complete(signals: list[SignalGroupingCompletion]) -> None:
        recorder.completions.append(signals)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[TeamSignalGroupingV2Workflow],
            activities=[fake_read, fake_type_examples, fake_embedding, fake_queries, fake_drop, fake_complete],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                TeamSignalGroupingV2Workflow.run,
                TeamSignalGroupingV2Input(team_id=1, pending_batch_keys=[FIRST_BATCH_KEY]),
                id=f"grouping-v2-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

            await _wait_until(lambda: recorder.reads.count(FIRST_BATCH_KEY) >= rounds_of_first_batch)
            await _wait_until(lambda: len(recorder.drops) >= 1)

            await handle.signal(TeamSignalGroupingV2Workflow.submit_batch, SECOND_BATCH_KEY)
            await _wait_until(lambda: SECOND_BATCH_KEY in recorder.reads)

            with suppress(RPCError):
                await env.client.get_workflow_handle(handle.id).terminate()


def _fast_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "products.signals.backend.temporal.grouping_v2.BATCH_COLLECT_TIMEOUT", timedelta(milliseconds=100)
    )
    monkeypatch.setattr("products.signals.backend.temporal.grouping_v2.RETRY_BACKOFF", timedelta(milliseconds=10))


@pytest.mark.asyncio
async def test_non_retryable_failure_drops_the_batch_without_retrying(monkeypatch: pytest.MonkeyPatch):
    _fast_collect(monkeypatch)
    recorder = _Recorder()

    await _drive(
        recorder,
        embedding_error=lambda: ApplicationError(
            "organization has not opted into AI data processing", non_retryable=True
        ),
        rounds_of_first_batch=1,
    )

    assert recorder.reads.count(FIRST_BATCH_KEY) == 1
    assert SECOND_BATCH_KEY in recorder.reads
    first_drop = recorder.drops[0]
    assert (first_drop.stage, first_drop.source_id) == ("grouping_prep", "issue-1")
    assert [completion.signal_id for completion in recorder.completions[0]] == ["signal-1"]
