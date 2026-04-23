import json
from datetime import UTC, datetime, timedelta
from typing import Optional

from django.conf import settings

import temporalio
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricGauge, RetryPolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.grouping import (
    TYPE_EXAMPLES_CACHE_TTL,
    FetchSignalTypeExamplesOutput,
    _process_signal_batch,
)
from products.signals.backend.temporal.metrics import team_meter_attrs
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ReadSignalsFromS3Input,
    ReadSignalsFromS3Output,
    TeamSignalGroupingV2Input,
)

PAUSE_SLEEP_SECONDS = 30
PAUSE_MAX_RUN_DURATION = timedelta(minutes=30)


def _pending_batches_gauge(team_id: int) -> MetricGauge:
    return (
        workflow.metric_meter()
        .with_additional_attributes(team_meter_attrs(team_id))
        .create_gauge(
            "signals_grouping_v2_pending_batches",
            "Number of signal batches currently buffered in the grouping v2 workflow, awaiting processing.",
        )
    )


def _batches_received_counter(team_id: int) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes(team_meter_attrs(team_id))
        .create_counter(
            "signals_grouping_v2_batches_received",
            "Number of signal batches received by the grouping v2 workflow via submit_batch.",
        )
    )


def _batches_processed_counter(team_id: int) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes(team_meter_attrs(team_id))
        .create_counter(
            "signals_grouping_v2_batches_processed",
            "Number of signal batches successfully processed by the grouping v2 workflow.",
        )
    )


def _batch_errors_counter(team_id: int) -> MetricCounter:
    return (
        workflow.metric_meter()
        .with_additional_attributes(team_meter_attrs(team_id))
        .create_counter(
            "signals_grouping_v2_batch_errors",
            "Number of signal batches that failed to be processed by the grouping v2 workflow.",
        )
    )


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
        self._cached_type_examples: Optional[FetchSignalTypeExamplesOutput] = None
        self._type_examples_fetched_at: Optional[datetime] = None
        self._paused_until: Optional[datetime] = None
        self._team_id: int | None = None

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"team-signal-grouping-v2-{team_id}"

    @temporalio.workflow.signal
    async def submit_batch(self, object_key: str) -> None:
        """Receive an S3 object key containing a batch of signals."""
        self._batch_key_buffer.append(object_key)
        # Temporal dispatches signal handlers only after `run()` has reached an await,
        # and `run()` sets `_team_id` before its first await — so in practice this is
        # always set. The guard protects against edge cases (replay during worker
        # restart, future signature changes) without regressing to an unlabeled metric.
        if self._team_id is not None:
            _batches_received_counter(self._team_id).add(1)
            _pending_batches_gauge(self._team_id).set(len(self._batch_key_buffer))

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

    @temporalio.workflow.run
    async def run(self, input: TeamSignalGroupingV2Input) -> None:
        # Restore state carried over from continue_as_new
        self._team_id = input.team_id
        # Back-fill the received counter for any batches that arrived via
        # signal-with-start before this workflow began executing. `pending_batch_keys`
        # is populated by continue_as_new and was already counted in the prior
        # instance, so only items already present in `_batch_key_buffer` from
        # signal handlers need to be counted here.
        pre_run_batches = len(self._batch_key_buffer)
        if pre_run_batches > 0:
            _batches_received_counter(input.team_id).add(pre_run_batches)
        self._batch_key_buffer.extend(input.pending_batch_keys)
        self._paused_until = input.paused_until
        start_time = workflow.now()
        _pending_batches_gauge(input.team_id).set(len(self._batch_key_buffer))

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
                continue

            # Pop the next key
            object_key = self._batch_key_buffer.pop(0)
            _pending_batches_gauge(input.team_id).set(len(self._batch_key_buffer))

            # Download the batch from S3
            read_result: ReadSignalsFromS3Output = await workflow.execute_activity(
                read_signals_from_s3_activity,
                ReadSignalsFromS3Input(object_key=object_key),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            signals: list[EmitSignalInputs] = read_result.signals

            # Invalidate type examples cache if stale
            now = workflow.now()
            cached = self._cached_type_examples
            if (
                self._type_examples_fetched_at is not None
                and (now - self._type_examples_fetched_at) > TYPE_EXAMPLES_CACHE_TTL
            ):
                cached = None

            try:
                # Per-signal drops are already tracked via the labeled
                # `signals_grouping_signals_batch_dropped` counter inside
                # `_process_signal_batch`, so we discard the aggregate count here.
                _dropped, type_examples = await _process_signal_batch(signals, cached_type_examples=cached)
                self._cached_type_examples = type_examples
                self._type_examples_fetched_at = self._type_examples_fetched_at if cached is not None else now
                _batches_processed_counter(input.team_id).add(1)
            except Exception:
                _batch_errors_counter(input.team_id).add(1)
                workflow.logger.exception(
                    "Failed to process signal batch",
                    team_id=input.team_id,
                    batch_size=len(signals),
                    object_key=object_key,
                )

            # continue_as_new after each batch to keep history bounded.
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
