"""Temporal activities. Each one only calls logic. Payloads carry ids and small results only."""

from functools import partial

import temporalio.activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections, on_asyncify_pool

from ..logic import highlights, pinned
from ..logic.news import (
    editions as news,
    runner as news_runner,
)
from .inputs import (
    FailNewsInputs,
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
    ResolvePinsInputs,
    ResolvePinsResult,
    WriteNewsInputs,
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
@close_db_connections
async def write_news_activity(inputs: WriteNewsInputs) -> None:
    async with Heartbeater():
        await news_runner.write_edition(inputs)


@temporalio.activity.defn
async def fail_news_activity(inputs: FailNewsInputs) -> None:
    await on_asyncify_pool(news.mark_failed)(inputs)
