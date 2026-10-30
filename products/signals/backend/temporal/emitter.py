import uuid
import hashlib
from dataclasses import dataclass
from datetime import timedelta

import temporalio
import posthoganalytics
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from products.signals.backend.temporal.buffer import SubmitSignalToBufferInput, submit_signal_to_buffer_activity
from products.signals.backend.temporal.drop_telemetry import capture_signal_dropped
from products.signals.backend.temporal.types import EmitSignalInputs

# Total time a signal can wait for buffer space, across all attempts.
SUBMIT_TO_BUFFER_TIMEOUT = timedelta(hours=3)
# Outlives the submit activity, so the workflow always sees the activity fail and can record the drop.
# A run that times out first ends silently after `signal_emitted`, and the signal has no outcome event.
EMITTER_RUN_TIMEOUT = SUBMIT_TO_BUFFER_TIMEOUT + timedelta(minutes=10)


@dataclass
class SignalEmitterInput:
    team_id: int
    signal: EmitSignalInputs


@temporalio.workflow.defn(name="signal-emitter")
class SignalEmitterWorkflow:
    """
    Ephemeral per-signal workflow that submits a signal to the buffer workflow
    via update. The update blocks if the buffer is full, providing backpressure.

    emit_signal() starts this fire-and-forget with either a unique ID or a caller-provided
    idempotency key.
    """

    @staticmethod
    def workflow_id_for(team_id: int, idempotency_key: str | None = None) -> str:
        suffix = hashlib.sha256(idempotency_key.encode()).hexdigest() if idempotency_key else str(uuid.uuid4())
        return f"signal-emitter-{team_id}-{suffix}"

    @temporalio.workflow.run
    async def run(self, input: SignalEmitterInput) -> None:
        with posthoganalytics.new_context(capture_exceptions=False):
            posthoganalytics.tag("team_id", input.team_id)
            posthoganalytics.tag("product", "signals")
            await self._run_impl(input)

    async def _run_impl(self, input: SignalEmitterInput) -> None:
        try:
            await workflow.execute_activity(
                submit_signal_to_buffer_activity,
                SubmitSignalToBufferInput(team_id=input.team_id, signal=input.signal),
                schedule_to_close_timeout=SUBMIT_TO_BUFFER_TIMEOUT,
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError as e:
            await capture_signal_dropped(input.signal, e, stage="emission")
            raise
