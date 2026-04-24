import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Optional

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import MetricGauge, RetryPolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.grouping import _process_signal_batch
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ReadSignalsFromS3Input,
    ReadSignalsFromS3Output,
    TeamSignalGroupingV2Input,
)

logger = structlog.get_logger(__name__)

PAUSE_SLEEP_SECONDS = 30
PAUSE_MAX_RUN_DURATION = timedelta(minutes=30)
BATCH_COLLECT_MAX_SIGNALS = 20
BATCH_COLLECT_TIMEOUT = timedelta(seconds=30)
RETRY_BACKOFF = timedelta(seconds=10)


@dataclass
class CollectedBatch:
    """Result of collecting signals from one or more S3 batches."""

    signals: list[EmitSignalInputs] = field(default_factory=list)
    object_keys: list[str] = field(default_factory=list)


@activity.defn
async def read_signals_from_s3_activity(input: ReadSignalsFromS3Input) -> ReadSignalsFromS3Output:
    raw = await sync_to_async(object_storage.read, thread_sensitive=False)(input.object_key)
    if raw is None:
        raise ValueError(f"Signal batch not found in S3: {input.object_key}")

    data = json.loads(raw)
    signals = [EmitSignalInputs(**item) for item in data]

    return ReadSignalsFromS3Output(signals=signals)


@temporalio.workflow.defn(name="team-signal-grouping-v2")
class TeamSignalGroupingV2Workflow:
    """
    Receives batch keys from BufferSignalsWorkflow, reads each batch from object
    storage, and processes it via _process_signal_batch().

    Supports pause/unpause and uses continue_as_new to keep history bounded.

    One instance per team (workflow ID: team-signal-grouping-v2-{team_id}).
    """

    def __init__(self) -> None:
        self._batch_key_buffer: list[str] = []
        self._paused_until: Optional[datetime] = None
        self._batch_buffer_size_gauge: Optional[MetricGauge] = None

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"team-signal-grouping-v2-{team_id}"

    @temporalio.workflow.signal
    async def submit_batch(self, object_key: str) -> None:
        """Receive an S3 object key containing a batch of signals."""
        self._batch_key_buffer.append(object_key)
        if self._batch_buffer_size_gauge is not None:
            self._batch_buffer_size_gauge.set(len(self._batch_key_buffer))

    @temporalio.workflow.signal
    async def set_paused_until(self, timestamp: datetime) -> None:
        """Pause the workflow until the given timestamp."""
        self._paused_until = timestamp

    @temporalio.workflow.signal
    async def clear_paused(self) -> None:
        """Clear the paused state."""
        self._paused_until = None

    @temporalio.workflow.query
    def get_paused_state(self) -> Optional[datetime]:
        """Return the paused-until timestamp, or None if not paused."""
        return self._paused_until

    def _is_paused(self) -> bool:
        return self._paused_until is not None and workflow.now() < self._paused_until

    def _continue_as_new(self, input: TeamSignalGroupingV2Input) -> None:
        workflow.continue_as_new(
            TeamSignalGroupingV2Input(
                team_id=input.team_id,
                pending_batch_keys=list(self._batch_key_buffer),
                paused_until=self._paused_until,
            )
        )

    async def _collect_next_batch(self) -> CollectedBatch:
        collected = CollectedBatch()
        deadline = workflow.now() + BATCH_COLLECT_TIMEOUT

        while len(collected.signals) < BATCH_COLLECT_MAX_SIGNALS:
            if workflow.now() >= deadline:
                break

            if not self._batch_key_buffer:
                try:
                    await workflow.wait_condition(
                        lambda: len(self._batch_key_buffer) > 0 or self._is_paused(),
                        timeout=deadline - workflow.now(),
                    )
                except TimeoutError:
                    break
                if self._is_paused() or not self._batch_key_buffer:
                    break

            object_key = self._batch_key_buffer.pop(0)
            if self._batch_buffer_size_gauge is not None:
                self._batch_buffer_size_gauge.set(len(self._batch_key_buffer))
            collected.object_keys.append(object_key)

            read_result: ReadSignalsFromS3Output = await workflow.execute_activity(
                read_signals_from_s3_activity,
                ReadSignalsFromS3Input(object_key=object_key),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            collected.signals.extend(read_result.signals)

        return collected

    @temporalio.workflow.run
    async def run(self, input: TeamSignalGroupingV2Input) -> None:
        # Restore state carried over from continue_as_new
        self._batch_key_buffer.extend(input.pending_batch_keys)
        self._paused_until = input.paused_until
        start_time = workflow.now()

        meter = workflow.metric_meter().with_additional_attributes({"team_id": str(input.team_id)})
        self._batch_buffer_size_gauge = meter.create_gauge(
            "signals_grouping_v2_batch_buffer_size",
            "Current number of signal batches buffered for processing in grouping v2",
        )
        self._batch_buffer_size_gauge.set(len(self._batch_key_buffer))

        while True:
            # If paused, sleep in 30s increments until unpaused or pause expires
            if self._is_paused():
                if (workflow.now() - start_time) > PAUSE_MAX_RUN_DURATION:
                    self._continue_as_new(input)
                await workflow.wait_condition(
                    lambda: not self._is_paused(),
                    timeout=timedelta(seconds=PAUSE_SLEEP_SECONDS),
                )
                continue

            # Wait for at least one batch key
            await workflow.wait_condition(lambda: len(self._batch_key_buffer) > 0)

            if self._is_paused():
                self._continue_as_new(input)

            # Collect signals from multiple batches until we hit the signal
            # count threshold or the collection timeout expires.
            collected = await self._collect_next_batch()

            if not collected.signals:
                # Could happen if we woke up due to pause; loop back around
                continue

            if self._is_paused():
                # Paused while collecting; stash collected keys back and loop
                self._batch_key_buffer = collected.object_keys + self._batch_key_buffer
                if self._batch_buffer_size_gauge is not None:
                    self._batch_buffer_size_gauge.set(len(self._batch_key_buffer))
                continue

            try:
                _dropped, _type_examples = await _process_signal_batch(collected.signals)
            except Exception:
                logger.exception(
                    "Failed to process signal batch",
                    team_id=input.team_id,
                    batch_size=len(collected.signals),
                    batch_keys=collected.object_keys,
                )
                # Stash keys back so they're retried after continue_as_new.
                # Sleep first to avoid hot-looping on deterministic failures.
                self._batch_key_buffer = collected.object_keys + self._batch_key_buffer
                if self._batch_buffer_size_gauge is not None:
                    self._batch_buffer_size_gauge.set(len(self._batch_key_buffer))
                await workflow.sleep(RETRY_BACKOFF)

            # continue_as_new after each processing round to keep history bounded.
            # Carry over any pending keys that arrived while we were processing.
            self._continue_as_new(input)

    # -- External interaction classmethods (called from Django) --

    @classmethod
    async def pause_until(cls, team_id: int, timestamp: datetime) -> None:
        """Pause the grouping workflow until the given timestamp. Starts the workflow if not running."""
        client = await async_connect()
        await client.start_workflow(
            cls.run,
            TeamSignalGroupingV2Input(team_id=team_id),
            id=cls.workflow_id_for(team_id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            run_timeout=timedelta(hours=3),
            start_signal="set_paused_until",
            start_signal_args=[timestamp],
        )

    @classmethod
    async def unpause(cls, team_id: int) -> bool:
        """Clear the paused state. Starts the workflow if not running. Returns whether it was actually paused."""
        client = await async_connect()
        was_paused = False
        try:
            handle = client.get_workflow_handle(cls.workflow_id_for(team_id))
            state = await handle.query(cls.get_paused_state)
            was_paused = state is not None and state > datetime.now(tz=UTC)
        except RPCError as e:
            if e.status != RPCStatusCode.NOT_FOUND:
                raise
        await client.start_workflow(
            cls.run,
            TeamSignalGroupingV2Input(team_id=team_id),
            id=cls.workflow_id_for(team_id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            run_timeout=timedelta(hours=3),
            start_signal="clear_paused",
            start_signal_args=[],
        )
        return was_paused

    @classmethod
    async def paused_state(cls, team_id: int) -> Optional[datetime]:
        """Query the paused-until timestamp. Returns None if the workflow isn't running."""
        client = await async_connect()
        try:
            handle = client.get_workflow_handle(cls.workflow_id_for(team_id))
            return await handle.query(cls.get_paused_state)
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return None
            raise
