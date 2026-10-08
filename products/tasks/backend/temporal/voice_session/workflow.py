import json
from datetime import timedelta

import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.tasks.backend.logic.services.voice_sessions import VoiceSessionRecord

from .activities import MONITOR_MAX_ATTEMPTS, VoiceSessionMonitorInput, monitor_voice_session

# Covers the close grace period and the final usage event after the deadline.
MONITOR_TIMEOUT_MARGIN = timedelta(minutes=2)


@temporalio.workflow.defn(name="desktop-voice-session")
class DesktopVoiceSessionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> VoiceSessionMonitorInput:
        data = json.loads(inputs[0])
        return VoiceSessionMonitorInput(
            record=VoiceSessionRecord(**data["record"]),
            started_at=data["started_at"],
            max_duration_seconds=data["max_duration_seconds"],
        )

    @temporalio.workflow.run
    async def run(self, input: VoiceSessionMonitorInput) -> None:
        await temporalio.workflow.execute_activity(
            monitor_voice_session,
            input,
            start_to_close_timeout=timedelta(seconds=input.max_duration_seconds) + MONITOR_TIMEOUT_MARGIN,
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=MONITOR_MAX_ATTEMPTS, initial_interval=timedelta(seconds=2)),
        )
