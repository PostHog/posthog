"""Temporal activities. Each one only calls logic. Payloads carry ids and small results only."""

from functools import partial

import temporalio.activity

from posthog.sync import database_sync_to_async

from ..logic import highlights, pinned
from ..logic.news import editions as news
from .inputs import (
    FailNewsInputs,
    FinalizeHighlightsInputs,
    GenerateNewsInputs,
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
    resolve = partial(pinned.resolve_pins, publish=partial(highlights.publish_pinned, inputs))
    return await database_sync_to_async(resolve, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def finalize_highlights_activity(inputs: FinalizeHighlightsInputs) -> None:
    await database_sync_to_async(highlights.finalize, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def collect_news_facts_activity(inputs: GenerateNewsInputs) -> bool:
    return await database_sync_to_async(news.collect_facts, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def write_news_activity(inputs: GenerateNewsInputs) -> None:
    await database_sync_to_async(news.write_edition, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def fail_news_activity(inputs: FailNewsInputs) -> None:
    await database_sync_to_async(news.mark_failed, thread_sensitive=False)(inputs)
