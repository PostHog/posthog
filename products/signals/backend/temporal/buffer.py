import json
import uuid
import random
import asyncio
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings

import structlog
import temporalio
import posthoganalytics
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import MetricCounter, RetryPolicy

from posthog.event_usage import groups
from posthog.models import Team
from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.facade.api import _telemetry_props_from_extra
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
@scoped_temporal()
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
@scoped_temporal()
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


def _emit_signal_buffered_event(team: Team, signal: EmitSignalInputs) -> None:
    """Fire the `signal_buffered` lifecycle event as a signal is handed off to the buffer."""
    posthoganalytics.capture(
        event="signal_buffered",
        distinct_id=str(team.uuid),
        # Mirror signal_emitted's shape so the two join on source_id: flattened scalar `extra`
        # only (nested customer-derived values dropped), core source_* keys win on conflict.
        properties={
            **_telemetry_props_from_extra(signal.extra),
            "source_product": signal.source_product,
            "source_type": signal.source_type,
            "source_id": signal.source_id,
        },
        groups=groups(team.organization, team),
    )


async def _capture_signal_buffered(signal: EmitSignalInputs) -> None:
    """Best-effort `signal_buffered` telemetry; never raises into the submit path.

    Pairs with `signal_emitted`, which fires when the per-signal emitter workflow is merely
    STARTED (facade/api.py). A signal whose emitter is killed by its 10-min run_timeout while
    backpressure-blocking never reaches here, so the emitted -> buffered gap isolates emit-handoff
    loss from later (grouping/report) loss — the previously-undifferentiated `emitted_unassigned`.
    """
    try:
        team = await Team.objects.select_related("organization").aget(pk=signal.team_id)
        _emit_signal_buffered_event(team, signal)
    except Exception as e:
        # Swallow: a failed analytics event must never break (or retry) signal submission.
        posthoganalytics.capture_exception(e)
        logger.exception(
            "Failed to capture signal_buffered event",
            team_id=signal.team_id,
            source_id=signal.source_id,
        )


@activity.defn
@scoped_temporal()
@close_db_connections
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

    # Emit the checkpoint BEFORE the buffer hand-off so the non-idempotent `submit_signal`
    # stays the activity's last operation. `submit_signal` durably appends with no dedupe key,
    # so any post-send work that lets the worker die mid-activity (SIGKILL / eviction / heartbeat
    # timeout — uncatchable) would retry the whole activity and re-send a duplicate signal. By
    # the time we reach here the emitter has cleared backpressure, so the emitted -> buffered gap
    # still isolates emit-handoff loss; a rare send-retry only re-fires this best-effort event.
    await _capture_signal_buffered(input.signal)

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
        self._signals_emitted_counters: dict[tuple[str, str], MetricCounter] = {}

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"buffer-signals-{team_id}"

    @temporalio.workflow.query
    def get_buffer_size(self) -> int:
        return len(self._signal_buffer)

    def _get_emitted_counter(self, team_id: int, source_product: str, source_type: str) -> MetricCounter:
        key = (source_product, source_type)
        if key not in self._signals_emitted_counters:
            meter = workflow.metric_meter().with_additional_attributes(
                {
                    "team_id": str(team_id),
                    "source_product": source_product,
                    "source_type": source_type,
                }
            )
            self._signals_emitted_counters[key] = meter.create_counter(
                "signals_emitted",
                "Number of signals emitted",
            )
        return self._signals_emitted_counters[key]

    @temporalio.workflow.signal
    async def submit_signal(self, signal: EmitSignalInputs) -> None:
        self._get_emitted_counter(signal.team_id, signal.source_product, signal.source_type).add(1)
        self._signal_buffer.append(signal)

    @temporalio.workflow.run
    async def run(self, input: BufferSignalsInput) -> None:
        with posthoganalytics.new_context(capture_exceptions=False):
            posthoganalytics.tag("team_id", input.team_id)
            posthoganalytics.tag("product", "signals")
            await self._run_impl(input)

    async def _run_impl(self, input: BufferSignalsInput) -> None:
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
                        SafetyFilterInput(
                            team_id=s.team_id,
                            description=s.description,
                            source_product=s.source_product,
                            source_type=s.source_type,
                            source_id=s.source_id,
                            weight=s.weight,
                            extra=s.extra,
                        ),
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
