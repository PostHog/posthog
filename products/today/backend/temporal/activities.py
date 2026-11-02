"""Temporal activities. Each one only calls logic. Payloads carry ids and small results only."""

import temporalio.activity

from posthog.sync import database_sync_to_async

from ..logic import highlights, pinned
from .inputs import (
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
    ResolvePinsInputs,
    ResolvePinsResult,
)


@temporalio.activity.defn
async def run_highlight_source_activity(inputs: HighlightSourceInputs) -> HighlightSourceResult:
    return await database_sync_to_async(highlights.run_source, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def resolve_pins_activity(inputs: ResolvePinsInputs) -> ResolvePinsResult:
    return await database_sync_to_async(pinned.resolve_pins, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def finalize_highlights_activity(inputs: FinalizeHighlightsInputs) -> None:
    await database_sync_to_async(highlights.finalize, thread_sensitive=False)(inputs)
