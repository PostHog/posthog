"""Temporal activities for suggested dashboards. Each one calls the logic and passes ids, never panels or pictures."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import temporalio.activity

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.metrics.backend.suggested_dashboards import discovery, generation
from products.metrics.backend.suggested_dashboards.analysis import analyze_team
from products.metrics.backend.suggested_dashboards.bank import sync_curated_templates
from products.metrics.backend.temporal.inputs import (
    DiscoveryInputs,
    FinishInputs,
    GenerateInputs,
    GenerationRequestInputs,
    RoundInputs,
    SuggestInputs,
    SuggestResult,
)

T = TypeVar("T")


async def _run(fn: Callable[[], T], *, team_id: int | None = None) -> T:
    def tagged() -> T:
        with tags_context(product=Product.METRICS, feature=Feature.ENRICHMENT, team_id=team_id):
            return fn()

    async with Heartbeater():
        return await database_sync_to_async(tagged, thread_sensitive=False)()


@temporalio.activity.defn
async def find_teams_to_analyze_activity(inputs: DiscoveryInputs) -> list[int]:
    def find() -> list[int]:
        sync_curated_templates()
        return discovery.teams_to_analyze()

    return await _run(find)


@temporalio.activity.defn
async def analyze_team_activity(inputs: SuggestInputs) -> SuggestResult:
    result = await _run(lambda: analyze_team(inputs.team_id, force=inputs.force), team_id=inputs.team_id)
    return SuggestResult(
        suggestion_count=result.suggestion_count,
        generation_requests=[
            GenerationRequestInputs(
                key=request.key,
                name=request.name,
                description=request.description,
                metric_names=list(request.metric_names),
            )
            for request in result.generation_requests
        ],
    )


@temporalio.activity.defn
async def start_generation_activity(inputs: GenerateInputs) -> str | None:
    request = generation.GenerationRequest(
        key=inputs.request.key,
        name=inputs.request.name,
        description=inputs.request.description,
        metric_names=tuple(inputs.request.metric_names),
    )
    return await _run(lambda: generation.start_generation(inputs.team_id, request), team_id=inputs.team_id)


@temporalio.activity.defn
async def draft_template_activity(template_id: str) -> int:
    return await _run(lambda: generation.draft_template(template_id))


@temporalio.activity.defn
async def render_preview_activity(inputs: RoundInputs) -> int | None:
    return await _run(lambda: generation.render_preview(inputs.template_id, inputs.round))


@temporalio.activity.defn
async def check_preview_activity(inputs: RoundInputs) -> bool:
    return await _run(lambda: generation.check_preview(inputs.template_id, inputs.round, revise=inputs.revise))


@temporalio.activity.defn
async def finish_generation_activity(inputs: FinishInputs) -> None:
    await _run(lambda: generation.finish_generation(inputs.template_id, error=inputs.error))
