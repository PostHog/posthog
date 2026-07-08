import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.error_tracking.backend.temporal.spike_event_cleanup.activities import cleanup_spike_events_activity
    from products.error_tracking.backend.temporal.spike_event_cleanup.types import (
        SpikeEventCleanupInputs,
        SpikeEventCleanupResult,
    )

WORKFLOW_NAME = "error-tracking-spike-event-cleanup"

ACTIVITY_RETRY_POLICY = common.RetryPolicy(maximum_attempts=1)
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(hours=2)


@workflow.defn(name=WORKFLOW_NAME)
class ErrorTrackingSpikeEventCleanupWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SpikeEventCleanupInputs:
        if inputs:
            data = json.loads(inputs[0])
            return SpikeEventCleanupInputs(**data)
        return SpikeEventCleanupInputs()

    @workflow.run
    async def run(self, inputs: SpikeEventCleanupInputs | None = None) -> SpikeEventCleanupResult:
        if inputs is None:
            inputs = SpikeEventCleanupInputs()

        return await workflow.execute_activity(
            cleanup_spike_events_activity,
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
