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
        if not (temporalio.workflow.patched(PINNED_NUMBERS_PATCH) and inputs.pins):
            await _finalize(inputs, list(await sources), [])
            return
        results, first = await asyncio.gather(sources, _resolve_pins(inputs, inputs.pins))
        pin_results = [first]
        await _finalize(inputs, list(results), pin_results)
        for _ in range(PIN_ATTEMPTS - 1):
            last = pin_results[-1]
            if not last.pending or last.failed:
                break
            await asyncio.sleep(PIN_RETRY_SECONDS)
            pin_results.append(await _resolve_pins(inputs, [pin for pin in inputs.pins if pin.key in last.pending]))
        if len(pin_results) > 1:
            await _finalize(inputs, list(results), pin_results)


async def _finalize(
    inputs: ComputeHighlightsInputs, results: list[HighlightSourceResult], pin_results: list[ResolvePinsResult]
) -> None:
    await temporalio.workflow.execute_activity(
        finalize_highlights_activity,
        FinalizeHighlightsInputs(
            team_id=inputs.team_id,
            highlights_id=inputs.highlights_id,
            results=results,
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
                pinned=[pin.key for pin in inputs.pins],
            ),
            start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
    except ActivityError:
        return HighlightSourceResult(source_name=source_name, found=None, failed=True)


async def _resolve_pins(inputs: ComputeHighlightsInputs, pins: list[PinnedNumber]) -> ResolvePinsResult:
    try:
        return await temporalio.workflow.execute_activity(
            resolve_pins_activity,
            ResolvePinsInputs(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                local_day=inputs.local_day,
                scopes=inputs.scopes,
                pins=pins,
            ),
            start_to_close_timeout=HIGHLIGHT_SOURCE_TIMEOUT,
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=2),
        )
    except ActivityError:
        return ResolvePinsResult(keys=[], found="[]", pending=[pin.key for pin in pins], failed=True)
