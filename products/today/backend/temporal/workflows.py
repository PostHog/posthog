"""Temporal workflows: generate one briefing, and start the scheduled ones before 8:00 local time."""

from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from ..logic.generate import ATTEMPT_TIMEOUT, ATTEMPTS, RETRY_INTERVAL, RUN_TIMEOUT
    from .activities import mark_failed_activity, start_due_briefings_activity, write_briefing_activity
    from .inputs import (
        GENERATE_WORKFLOW_NAME,
        SCHEDULER_WORKFLOW_NAME,
        GenerateBriefingInputs,
        MarkFailedInputs,
        SchedulerInputs,
    )

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
            # A retry is safe: an attempt only reads, makes one LLM call and overwrites the same row.
            await temporalio.workflow.execute_activity(
                write_briefing_activity,
                inputs,
                start_to_close_timeout=ATTEMPT_TIMEOUT,
                schedule_to_close_timeout=RUN_TIMEOUT,
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=ATTEMPTS, initial_interval=RETRY_INTERVAL),
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
