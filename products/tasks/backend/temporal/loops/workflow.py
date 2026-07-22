from datetime import timedelta

import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import run_loop_trigger_activity


@temporalio.workflow.defn(name="run-loop")
class RunLoopWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        return inputs[0]

    @temporalio.workflow.run
    async def run(self, loop_trigger_id: str) -> None:
        await temporalio.workflow.execute_activity(
            run_loop_trigger_activity,
            loop_trigger_id,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
