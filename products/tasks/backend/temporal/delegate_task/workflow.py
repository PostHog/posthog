from datetime import timedelta

import temporalio
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

from .activities import (
    DelegateTaskInput,
    FailDelegatedRunInput,
    brief_task_run,
    dispatch_briefed_run,
    fail_delegated_run,
)


def _brief_failure_message(error: ActivityError) -> str:
    cause = error.cause
    detail = cause.message if isinstance(cause, ApplicationError) else str(cause or error)
    return f"Could not brief the delegated run: {detail}"


@temporalio.workflow.defn(name="delegate-task")
class DelegateTaskWorkflow(PostHogWorkflow):
    """Brief a delegated run, then hand it to the process-task workflow.

    The run row already exists when this starts. A brief that fails after its retries marks
    the run failed, so the caller sees the outcome on the run it was given at creation.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DelegateTaskInput:
        return DelegateTaskInput(run_id=inputs[0])

    @temporalio.workflow.run
    async def run(self, input: DelegateTaskInput) -> None:
        try:
            await temporalio.workflow.execute_activity(
                brief_task_run,
                input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=2, non_retryable_error_types=["BriefError", "RunNotBriefable"]
                ),
            )
        except ActivityError as error:
            await temporalio.workflow.execute_activity(
                fail_delegated_run,
                FailDelegatedRunInput(run_id=input.run_id, error_message=_brief_failure_message(error)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return

        await temporalio.workflow.execute_activity(
            dispatch_briefed_run,
            input,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
