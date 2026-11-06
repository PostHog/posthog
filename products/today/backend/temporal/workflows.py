"""Temporal workflows: compute highlights."""

import asyncio
from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from .activities import (
        collect_news_facts_activity,
        fail_news_activity,
        finalize_highlights_activity,
        resolve_pins_activity,
        run_highlight_source_activity,
        write_news_activity,
    )
    from .inputs import (
        HIGHLIGHTS_WORKFLOW_NAME,
        NEWS_WORKFLOW_NAME,
        ComputeHighlightsInputs,
        FailNewsInputs,
        FinalizeHighlightsInputs,
        GenerateNewsInputs,
        HighlightSourceInputs,
        HighlightSourceResult,
        ResolvePinsInputs,
        ResolvePinsResult,
    )

HIGHLIGHT_SOURCE_TIMEOUT = timedelta(seconds=180)
HIGHLIGHT_SOURCE_TOTAL_TIMEOUT = timedelta(seconds=240)
FINALIZE_HIGHLIGHTS_TIMEOUT = timedelta(seconds=30)
PINNED_NUMBERS_PATCH = "today-pinned-numbers"
COLLECT_NEWS_TIMEOUT = timedelta(seconds=180)
WRITE_NEWS_TIMEOUT = timedelta(minutes=2)
FAIL_NEWS_TIMEOUT = timedelta(seconds=30)
MAX_NEWS_ERROR_LENGTH = 2000


@temporalio.workflow.defn(name=HIGHLIGHTS_WORKFLOW_NAME)
class ComputeTodayHighlightsWorkflow(PostHogWorkflow):
    inputs_cls = ComputeHighlightsInputs

    @temporalio.workflow.run
    async def run(self, inputs: ComputeHighlightsInputs) -> None:
        sources = asyncio.gather(*(_run_source(inputs, name) for name in inputs.source_names))
        temporalio.workflow.deprecate_patch(PINNED_NUMBERS_PATCH)
        if inputs.pins:
            results, pinned = await asyncio.gather(sources, _resolve_pins(inputs))
        else:
            results, pinned = await sources, ResolvePinsResult(found="[]")
        await temporalio.workflow.execute_activity(
            finalize_highlights_activity,
            FinalizeHighlightsInputs(
                team_id=inputs.team_id,
                highlights_id=inputs.highlights_id,
                results=list(results),
                pins=inputs.pins,
                pinned=pinned.found,
                pins_failed=pinned.failed,
            ),
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
                pinned=[pin.key for pin in inputs.pins],
                highlights_id=inputs.highlights_id,
            ),
            start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
            schedule_to_close_timeout=HIGHLIGHT_SOURCE_TOTAL_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
    except ActivityError:
        return HighlightSourceResult(source_name=source_name, found=None, failed=True)


async def _resolve_pins(inputs: ComputeHighlightsInputs) -> ResolvePinsResult:
    try:
        result = await temporalio.workflow.execute_activity(
            resolve_pins_activity,
            ResolvePinsInputs(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                local_day=inputs.local_day,
                scopes=inputs.scopes,
                pins=inputs.pins,
                highlights_id=inputs.highlights_id,
            ),
            start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )
    except ActivityError:
        return ResolvePinsResult(found="[]", failed=True)
    return result


@temporalio.workflow.defn(name=NEWS_WORKFLOW_NAME)
class GenerateTodayNewsWorkflow(PostHogWorkflow):
    inputs_cls = GenerateNewsInputs

    @temporalio.workflow.run
    async def run(self, inputs: GenerateNewsInputs) -> None:
        try:
            proceed = await temporalio.workflow.execute_activity(
                collect_news_facts_activity,
                inputs,
                start_to_close_timeout=COLLECT_NEWS_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
            )
            if proceed:
                await temporalio.workflow.execute_activity(
                    write_news_activity,
                    inputs,
                    start_to_close_timeout=WRITE_NEWS_TIMEOUT,
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                )
        except ActivityError as error:
            await temporalio.workflow.execute_activity(
                fail_news_activity,
                FailNewsInputs(
                    team_id=inputs.team_id,
                    edition_id=inputs.edition_id,
                    error=str(error.cause or error)[:MAX_NEWS_ERROR_LENGTH],
                ),
                start_to_close_timeout=FAIL_NEWS_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
