import temporalio
from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

# Activities live behind Django imports, which Temporal's workflow sandbox blocks.
# Mark them as pass-through; workflow code only passes them as references to
# `execute_activity`, never calls them.
with workflow.unsafe.imports_passed_through():
    from products.logs.backend.temporal.volume_tick.activities import (
        VolumeTickInput,
        VolumeTickOutput,
        volume_tick_heartbeat_activity,
    )

from products.logs.backend.temporal.volume_tick.constants import ACTIVITY_RETRY_POLICY, ACTIVITY_TIMEOUT, WORKFLOW_NAME


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class LogsVolumeTickWorkflow(PostHogWorkflow):
    """One tick of the log volume rollup. A skeleton that writes nothing: it runs
    the every-minute schedule end to end and observes what the real tick would do
    (teams with logs, the due bucket, the minute-shard cohort) before any
    aggregation logic lands."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> VolumeTickInput:
        return VolumeTickInput()

    @temporalio.workflow.run
    async def run(self, input: VolumeTickInput) -> VolumeTickOutput:
        return await workflow.execute_activity(
            volume_tick_heartbeat_activity,
            input,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
