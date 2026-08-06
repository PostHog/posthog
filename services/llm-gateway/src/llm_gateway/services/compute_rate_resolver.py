from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog

from llm_gateway.auth.service import upstream_auth_header
from llm_gateway.config import get_settings

if TYPE_CHECKING:
    from fastapi import Request
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


@dataclass
class ComputeRateStatus:
    rate_cards: list[dict[str, object]] | None = None
    error: str | None = None


def _redis_key(team_id: int) -> str:
    return f"compute_rates:team:{team_id}"


async def resolve_compute_rates(request: Request, team_id: int | None) -> ComputeRateStatus:
    if team_id is None:
        return ComputeRateStatus()
    auth_header = upstream_auth_header(request)
    if not auth_header:
        return ComputeRateStatus()
    resolver: ComputeRateResolver = request.app.state.compute_rate_resolver
    try:
        return await resolver.get_rates(team_id, auth_header)
    except Exception:
        logger.warning("compute_rate_resolve_failed", team_id=team_id, exc_info=True)
        return ComputeRateStatus()


class ComputeRateResolver:
    def __init__(self, redis: Redis | None, http_client: httpx.AsyncClient):
        self._redis = redis
        self._http = http_client
        self._cache_ttl = get_settings().quota_cache_ttl

    async def get_rates(self, team_id: int, auth_header: str) -> ComputeRateStatus:
        cached = await self._get_cached(team_id)
        if cached is not None:
            return cached
        status = await self._fetch(team_id, auth_header)
        await self._set_cached(team_id, status)
        return status

    async def _fetch(self, team_id: int, auth_header: str) -> ComputeRateStatus:
        base_url = get_settings().posthog_api_base_url
        if not base_url:
            return ComputeRateStatus()
        response = await self._http.get(
            f"{base_url.rstrip('/')}/api/projects/{team_id}/sandbox_compute_rate_cards/",
            headers={"Authorization": auth_header},
            timeout=2.0,
        )
        response.raise_for_status()
        return _parse_status(response.json())

    async def _get_cached(self, team_id: int) -> ComputeRateStatus | None:
        if not self._redis:
            return None
        try:
            value = await self._redis.get(_redis_key(team_id))
            return _parse_status(json.loads(value.decode())) if value is not None else None
        except Exception:
            logger.debug("compute_rate_cache_read_failed", team_id=team_id)
            return None

    async def _set_cached(self, team_id: int, status: ComputeRateStatus) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(
                _redis_key(team_id),
                json.dumps({"rate_cards": status.rate_cards, "error": status.error}),
                ex=self._cache_ttl,
            )
        except Exception:
            logger.debug("compute_rate_cache_write_failed", team_id=team_id)


def _parse_status(data: object) -> ComputeRateStatus:
    if not isinstance(data, dict):
        return ComputeRateStatus()
    raw_rate_cards = data.get("rate_cards")
    rate_cards = (
        raw_rate_cards
        if isinstance(raw_rate_cards, list) and all(isinstance(card, dict) for card in raw_rate_cards)
        else None
    )
    raw_error = data.get("error")
    error = raw_error if raw_error == "invalid_configuration" else None
    return ComputeRateStatus(rate_cards=rate_cards, error=error)
