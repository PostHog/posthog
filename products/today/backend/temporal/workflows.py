"""Temporal workflows: generate one briefing, start the scheduled ones before 8:00 local time, and compute highlights."""

import asyncio
from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from ..logic.generate import ATTEMPT_TIMEOUT, ATTEMPTS, RETRY_INTERVAL, RUN_TIMEOUT
    from .activities import (
        finalize_highlights_activity,
        mark_failed_activity,
        run_highlight_source_activity,
        start_due_briefings_activity,
        write_briefing_activity,
    )
    from .inputs import (
        GENERATE_WORKFLOW_NAME,
        HIGHLIGHTS_WORKFLOW_NAME,
        SCHEDULER_WORKFLOW_NAME,
        ComputeHighlightsInputs,
        FinalizeHighlightsInputs,
        GenerateBriefingInputs,
        HighlightSourceInputs,
        HighlightSourceResult,
        MarkFailedInputs,
        SchedulerInputs,
    )

MARK_FAILED_TIMEOUT = timedelta(seconds=30)
SCHEDULER_TIMEOUT = timedelta(minutes=10)
HIGHLIGHT_SOURCE_TIMEOUT = timedelta(seconds=30)
FINALIZE_HIGHLIGHTS_TIMEOUT = timedelta(seconds=30)


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


@temporalio.workflow.defn(name=HIGHLIGHTS_WORKFLOW_NAME)
class ComputeTodayHighlightsWorkflow(PostHogWorkflow):
    inputs_cls = ComputeHighlightsInputs

    @temporalio.workflow.run
    async def run(self, inputs: ComputeHighlightsInputs) -> None:
        results = await asyncio.gather(*(_run_source(inputs, name) for name in inputs.source_names))
        await temporalio.workflow.execute_activity(
            finalize_highlights_activity,
            FinalizeHighlightsInputs(team_id=inputs.team_id, highlights_id=inputs.highlights_id, results=list(results)),
            start_to_close_timeout=FINALIZE_HIGHLIGHTS_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
        )


async def _run_source(inputs: ComputeHighlightsInputs, source_name: str) -> HighlightSourceResult:
    try:
        return await temporalio.workflow.execute_activity(
            run_highlight_source_activity,
            HighlightSourceInputs(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                local_day=inputs.local_day,
                scopes=inputs.scopes,
                source_name=source_name,
            ),
            start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
    except ActivityError:
        return HighlightSourceResult(source_name=source_name, found=None, failed=True)
