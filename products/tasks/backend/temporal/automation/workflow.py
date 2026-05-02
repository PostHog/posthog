from datetime import timedelta

import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import run_task_automation_activity


@temporalio.workflow.defn(name="run-task-automation")
class RunTaskAutomationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        return inputs[0]

    @temporalio.workflow.run
    async def run(self, automation_id: str) -> None:
        await temporalio.workflow.execute_activity(
            run_task_automation_activity,
            automation_id,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
