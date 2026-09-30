"""Temporal workflows: generate one briefing, and start the scheduled ones before 8:00 local time."""

from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from .activities import (
        collect_and_draft_activity,
        mark_failed_activity,
        start_due_briefings_activity,
        write_and_check_activity,
    )
    from .inputs import (
        GENERATE_WORKFLOW_NAME,
        SCHEDULER_WORKFLOW_NAME,
        GenerateBriefingInputs,
        MarkFailedInputs,
        SchedulerInputs,
    )

COLLECT_TIMEOUT = timedelta(seconds=90)
WRITE_TIMEOUT = timedelta(seconds=150)
MARK_FAILED_TIMEOUT = timedelta(seconds=30)
SCHEDULER_TIMEOUT = timedelta(minutes=10)


def _error_message(error: Exception) -> str:
    if isinstance(error, ActivityError) and error.cause is not None:
        return str(error.cause)
    return str(error)


@temporalio.workflow.defn(name=GENERATE_WORKFLOW_NAME)
class GenerateTodayBriefingWorkflow(PostHogWorkflow):
    inputs_cls = GenerateBriefingInputs

    @temporalio.workflow.run
    async def run(self, inputs: GenerateBriefingInputs) -> None:
        try:
            eligible = await temporalio.workflow.execute_activity(
                collect_and_draft_activity,
                inputs,
                start_to_close_timeout=COLLECT_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
            )
            if not eligible:
                return
            # One attempt: a retry would pay for the LLM again. The draft stays when it fails.
            await temporalio.workflow.execute_activity(
                write_and_check_activity,
                inputs,
                start_to_close_timeout=WRITE_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
            )
        except Exception as error:
            await temporalio.workflow.execute_activity(
                mark_failed_activity,
                MarkFailedInputs(team_id=inputs.team_id, briefing_id=inputs.briefing_id, error=_error_message(error)),
                start_to_close_timeout=MARK_FAILED_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )


@temporalio.workflow.defn(name=SCHEDULER_WORKFLOW_NAME)
class TodayBriefingSchedulerWorkflow(PostHogWorkflow):
    inputs_cls = SchedulerInputs

    @temporalio.workflow.run
    async def run(self, inputs: SchedulerInputs) -> int:
        return await temporalio.workflow.execute_activity(
            start_due_briefings_activity,
            inputs,
            start_to_close_timeout=SCHEDULER_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
