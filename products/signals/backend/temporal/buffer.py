import json
import uuid
import random
import asyncio
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.safety_filter import SafetyFilterInput, safety_filter_activity
from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs, TeamSignalGroupingV2Input

logger = structlog.get_logger(__name__)

# TODO: Check if the size of the buffer doesn't overload memory for the Temporal workflow handling the batch
BUFFER_MAX_SIZE = 20
BUFFER_FLUSH_TIMEOUT_SECONDS = 5

OBJECT_STORAGE_SIGNALS_PREFIX = "signals/signal_batches"


@dataclass
class FlushBufferInput:
    team_id: int
    signals: list[EmitSignalInputs]


@dataclass
class FlushBufferOutput:
    object_key: str
    signal_count: int


@activity.defn
async def flush_signals_to_s3_activity(input: FlushBufferInput) -> FlushBufferOutput:
    batch_id = str(uuid.uuid4())
    object_key = f"{OBJECT_STORAGE_SIGNALS_PREFIX}/{batch_id}"

    payload = json.dumps([asdict(s) for s in input.signals])
    await sync_to_async(object_storage.write, thread_sensitive=False)(object_key, payload)

    logger.info(
        "signals_buffer.flushed_to_s3",
        team_id=input.team_id,
        object_key=object_key,
        signal_count=len(input.signals),
    )

    return FlushBufferOutput(object_key=object_key, signal_count=len(input.signals))


@dataclass
class SignalWithStartGroupingV2Input:
    team_id: int
    object_key: str


@activity.defn
async def signal_with_start_grouping_v2_activity(input: SignalWithStartGroupingV2Input) -> None:
    """Signal-with-start the grouping v2 workflow, creating it if it doesn't exist."""
    client = await async_connect()
    await client.start_workflow(
        TeamSignalGroupingV2Workflow.run,
        TeamSignalGroupingV2Input(team_id=input.team_id),
        id=TeamSignalGroupingV2Workflow.workflow_id_for(input.team_id),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        run_timeout=timedelta(hours=3),
        start_signal="submit_batch",
        start_signal_args=[input.object_key],
    )


@dataclass
class SubmitSignalToBufferInput:
    team_id: int
    signal: EmitSignalInputs


BACKPRESSURE_POLL_INTERVAL_SECONDS = 1


@activity.defn
async def submit_signal_to_buffer_activity(input: SubmitSignalToBufferInput) -> None:
    """Poll the buffer workflow's size via query, then send the signal once there's space."""
    client = await async_connect()
    handle = client.get_workflow_handle(BufferSignalsWorkflow.workflow_id_for(input.team_id))

    while True:
        activity.heartbeat()
        buffer_size = await handle.query(BufferSignalsWorkflow.get_buffer_size)
        if buffer_size < BUFFER_MAX_SIZE:
            break
        jitter = random.uniform(0, BACKPRESSURE_POLL_INTERVAL_SECONDS)
        await asyncio.sleep(BACKPRESSURE_POLL_INTERVAL_SECONDS + jitter)

    await handle.signal(BufferSignalsWorkflow.submit_signal, input.signal)


@temporalio.workflow.defn(name="buffer-signals")
class BufferSignalsWorkflow:
    """
    Buffers signals and flushes batch object keys to grouping v2.

    One instance per team (workflow ID: buffer-signals-{team_id}).
    Uses continue_as_new after each flush to keep history bounded.
    """

    def __init__(self) -> None:
        self._signal_buffer: list[EmitSignalInputs] = []

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"buffer-signals-{team_id}"

    @temporalio.workflow.query
    def get_buffer_size(self) -> int:
        return len(self._signal_buffer)

    @temporalio.workflow.signal
    async def submit_signal(self, signal: EmitSignalInputs) -> None:
        self._signal_buffer.append(signal)

    @temporalio.workflow.run
    async def run(self, input: BufferSignalsInput) -> None:
        self._signal_buffer.extend(input.pending_signals)

        while True:
            # Wait for at least one signal
            await workflow.wait_condition(lambda: len(self._signal_buffer) > 0)

            # Wait until buffer is full or timeout expires since oldest signal arrived
            if len(self._signal_buffer) < BUFFER_MAX_SIZE:
                try:
                    await workflow.wait_condition(
                        lambda: len(self._signal_buffer) >= BUFFER_MAX_SIZE,
                        timeout=timedelta(seconds=BUFFER_FLUSH_TIMEOUT_SECONDS),
                    )
                except TimeoutError:
                    pass

            # Drain buffer
            batch = list(self._signal_buffer)
            self._signal_buffer.clear()

            # Filter out malicious signals
            safety_results = await asyncio.gather(
                *[
                    workflow.execute_activity(
                        safety_filter_activity,
                        SafetyFilterInput(description=s.description),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    for s in batch
                ]
            )
            safe_signals: list[EmitSignalInputs] = []
            for signal, result in zip(batch, safety_results):
                if result.safe:
                    safe_signals.append(signal)
                else:
                    logger.warning(
                        "Safety filter dropped signal",
                        threat_type=result.threat_type,
                        team_id=signal.team_id,
                        source_product=signal.source_product,
                        source_type=signal.source_type,
                        source_id=signal.source_id,
                    )
            batch = safe_signals

            if not batch:
                # Compact history even when no safe signals remain — without
                # continue_as_new, repeated all-unsafe batches would grow
                # Temporal history unboundedly.
                if len(self._signal_buffer) < BUFFER_MAX_SIZE:
                    workflow.continue_as_new(
                        BufferSignalsInput(
                            team_id=input.team_id,
                            pending_signals=list(self._signal_buffer),
                        )
                    )
                continue

            # Flush to object storage
            flush_result: FlushBufferOutput = await workflow.execute_activity(
                flush_signals_to_s3_activity,
                FlushBufferInput(team_id=input.team_id, signals=batch),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Signal-with-start the grouping v2 workflow (creates it if not running)
            await workflow.execute_activity(
                signal_with_start_grouping_v2_activity,
                SignalWithStartGroupingV2Input(team_id=input.team_id, object_key=flush_result.object_key),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # If the buffer is already full again, loop to flush immediately
            # rather than continue_as_new (avoids losing throughput to workflow restart).
            if len(self._signal_buffer) < BUFFER_MAX_SIZE:
                workflow.continue_as_new(
                    BufferSignalsInput(
                        team_id=input.team_id,
                        pending_signals=list(self._signal_buffer),
                    )
                )
