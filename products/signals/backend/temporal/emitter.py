import uuid
from dataclasses import dataclass
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from products.signals.backend.temporal.buffer import SubmitSignalToBufferInput, submit_signal_to_buffer_activity
from products.signals.backend.temporal.types import EmitSignalInputs


@dataclass
class SignalEmitterInput:
    team_id: int
    signal: EmitSignalInputs


@temporalio.workflow.defn(name="signal-emitter")
class SignalEmitterWorkflow:
    """
    Ephemeral per-signal workflow that submits a signal to the buffer workflow
    via update. The update blocks if the buffer is full, providing backpressure.

    emit_signal() starts this fire-and-forget with a unique ID per signal.
    """

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"signal-emitter-{team_id}-{uuid.uuid4()}"

    @temporalio.workflow.run
    async def run(self, input: SignalEmitterInput) -> None:
        await workflow.execute_activity(
            submit_signal_to_buffer_activity,
            SubmitSignalToBufferInput(team_id=input.team_id, signal=input.signal),
            start_to_close_timeout=timedelta(hours=1),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
