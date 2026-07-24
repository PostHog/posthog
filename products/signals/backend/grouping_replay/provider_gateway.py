"""Django-aware provider adapters for PostHog's team-attributed LLM gateway."""

from __future__ import annotations

import asyncio
from typing import Any

from posthog.api.embedding_worker import EmbeddingResponse, async_generate_embedding
from posthog.llm.gateway_client import get_async_anthropic_gateway_client
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.grouping_replay.providers import ProviderSet

MAX_EMBEDDING_HTTP_CONCURRENCY = 8


class _AnthropicAdapter:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def generate_signature(
        self,
        *,
        model: str,
        system_prompt: str,
        signal_payload: str,
    ) -> str:
        response = await self._client.messages.create(
            model=model,
            max_tokens=700,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": signal_payload}],
        )
        return "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")

    async def complete(self, *, model: str, prompt: str, max_tokens: int) -> str:
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")


class _PostHogEmbeddingAdapter:
    def __init__(self, team_id: int) -> None:
        self._team_id = team_id
        self._team: Team | None = None
        self._semaphore = asyncio.Semaphore(MAX_EMBEDDING_HTTP_CONCURRENCY)

    async def _get_team(self) -> Team:
        if self._team is None:
            self._team = await database_sync_to_async(Team.objects.get)(pk=self._team_id)
        return self._team

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        team = await self._get_team()
        worker_model = "text-embedding-3-small-1536" if model == "text-embedding-3-small" else model

        async def embed_one(text: str) -> EmbeddingResponse:
            async with self._semaphore:
                return await async_generate_embedding(team, text, model=worker_model)

        responses = await asyncio.gather(*(embed_one(text) for text in texts))
        return [[float(value) for value in response.embedding] for response in responses]


def gateway_provider_set(team_id: int) -> ProviderSet:
    """Build providers attributed to ``team_id`` through the Signals gateway route."""

    anthropic = _AnthropicAdapter(get_async_anthropic_gateway_client(product="signals", team_id=team_id))
    embeddings = _PostHogEmbeddingAdapter(team_id)

    async def close() -> None:
        await anthropic._client.close()

    return ProviderSet(signatures=anthropic, embeddings=embeddings, oracle=anthropic, aclose=close)
