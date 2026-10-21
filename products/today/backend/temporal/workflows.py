"""Temporal workflows: compute highlights."""

import asyncio
from datetime import timedelta

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from .activities import finalize_highlights_activity, resolve_pins_activity, run_highlight_source_activity
    from .inputs import (
        HIGHLIGHTS_WORKFLOW_NAME,
        ComputeHighlightsInputs,
        FinalizeHighlightsInputs,
        HighlightSourceInputs,
        HighlightSourceResult,
        PinnedNumber,
        ResolvePinsInputs,
        ResolvePinsResult,
    )

HIGHLIGHT_SOURCE_TIMEOUT = timedelta(seconds=60)
FINALIZE_HIGHLIGHTS_TIMEOUT = timedelta(seconds=30)
PIN_ATTEMPTS = 5
PIN_RETRY_SECONDS = 5
PINNED_NUMBERS_PATCH = "today-pinned-numbers"


@temporalio.workflow.defn(name=HIGHLIGHTS_WORKFLOW_NAME)
class ComputeTodayHighlightsWorkflow(PostHogWorkflow):
    inputs_cls = ComputeHighlightsInputs

    @temporalio.workflow.run
    async def run(self, inputs: ComputeHighlightsInputs) -> None:
        sources = asyncio.gather(*(_run_source(inputs, name) for name in inputs.source_names))
        if temporalio.workflow.patched(PINNED_NUMBERS_PATCH) and inputs.pins:
            results, pin_results = await asyncio.gather(sources, _resolve_pins(inputs))
        else:
            results, pin_results = await sources, []
        await temporalio.workflow.execute_activity(
            finalize_highlights_activity,
            FinalizeHighlightsInputs(
                team_id=inputs.team_id,
                highlights_id=inputs.highlights_id,
                results=list(results),
                pins=inputs.pins,
                pin_results=pin_results,
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
            ),
            start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
    except ActivityError:
        return HighlightSourceResult(source_name=source_name, found=None, failed=True)


async def _resolve_pins(inputs: ComputeHighlightsInputs) -> list[ResolvePinsResult]:
    results: list[ResolvePinsResult] = []
    remaining: list[PinnedNumber] = inputs.pins
    for attempt in range(PIN_ATTEMPTS):
        if attempt:
            await asyncio.sleep(PIN_RETRY_SECONDS)
        try:
            result = await temporalio.workflow.execute_activity(
                resolve_pins_activity,
                ResolvePinsInputs(
                    team_id=inputs.team_id,
                    user_id=inputs.user_id,
                    local_day=inputs.local_day,
                    scopes=inputs.scopes,
                    pins=remaining,
                ),
                start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
            )
        except ActivityError:
            return [
                *results,
                ResolvePinsResult(keys=[], found="[]", pending=[pin.key for pin in remaining], failed=True),
            ]
        results.append(result)
        if not result.pending:
            break
        remaining = [pin for pin in remaining if pin.key in result.pending]
    return results
