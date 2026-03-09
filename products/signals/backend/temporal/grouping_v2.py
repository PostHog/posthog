import json
from datetime import datetime, timedelta
from typing import Optional

import temporalio
from asgiref.sync import sync_to_async
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.storage import object_storage

from products.signals.backend.temporal.grouping import (
    TYPE_EXAMPLES_CACHE_TTL,
    FetchSignalTypeExamplesOutput,
    _process_signal_batch,
)
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ReadSignalsFromS3Input,
    ReadSignalsFromS3Output,
    TeamSignalGroupingV2Input,
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
    V2 grouping workflow that receives S3 object keys (from BufferSignalsWorkflow)
    instead of raw signals. Downloads each batch from S3 and processes it via
    _process_signal_batch. S3 objects are cleaned up by lifecycle policies.

    Buffers pending object keys in memory. Calls continue_as_new after processing
    each batch, carrying over any remaining keys.

    One instance per team (workflow ID: team-signal-grouping-v2-{team_id}).
    """

    def __init__(self) -> None:
        self._batch_key_buffer: list[str] = []
        self._cached_type_examples: Optional[FetchSignalTypeExamplesOutput] = None
        self._type_examples_fetched_at: Optional[datetime] = None

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"team-signal-grouping-v2-{team_id}"

    @temporalio.workflow.signal
    async def submit_batch(self, object_key: str) -> None:
        """Receive an S3 object key containing a batch of signals."""
        self._batch_key_buffer.append(object_key)

    @temporalio.workflow.run
    async def run(self, input: TeamSignalGroupingV2Input) -> None:
        # Restore any keys carried over from continue_as_new
        self._batch_key_buffer.extend(input.pending_batch_keys)

        while True:
            # Wait for at least one batch key
            await workflow.wait_condition(lambda: len(self._batch_key_buffer) > 0)

            # Pop the next key
            object_key = self._batch_key_buffer.pop(0)

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
                dropped, type_examples = await _process_signal_batch(signals, cached_type_examples=cached)
                self._cached_type_examples = type_examples
                self._type_examples_fetched_at = self._type_examples_fetched_at if cached is not None else now
            except Exception:
                workflow.logger.exception(
                    "Failed to process signal batch",
                    team_id=input.team_id,
                    batch_size=len(signals),
                    object_key=object_key,
                )

            # continue_as_new after each batch to keep history bounded.
            # Carry over any pending keys that arrived while we were processing.
            workflow.continue_as_new(
                TeamSignalGroupingV2Input(
                    team_id=input.team_id,
                    pending_batch_keys=list(self._batch_key_buffer),
                )
            )
