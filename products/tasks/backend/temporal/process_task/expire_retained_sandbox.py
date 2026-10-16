from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox


@workflow.defn(name="expire-retained-task-sandbox")
class ExpireRetainedSandboxWorkflow(PostHogWorkflow):
    inputs_cls = CleanupSandboxInput

    @workflow.run
    async def run(self, input: CleanupSandboxInput) -> None:
        remaining = (
            max(0, input.recovery_deadline + 60 - workflow.now().timestamp())
            if input.recovery_deadline is not None
            else 15 * 60
        )
        await workflow.sleep(timedelta(seconds=remaining))
        await workflow.execute_activity(
            cleanup_sandbox,
            CleanupSandboxInput(sandbox_id=input.sandbox_id, run_id=input.run_id, raise_on_error=True),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=5)),
        )
