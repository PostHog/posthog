"""Resolves a team's quota state via the PostHog API quota_limits endpoint.

Mirrors :mod:`llm_gateway.services.plan_resolver` — forwards the caller's
``Authorization`` header to ``GET /api/projects/{team_id}/quota_limits/`` and
caches the result per team-and-resource in the gateway's own Redis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from llm_gateway.config import get_settings

if TYPE_CHECKING:
    import httpx
    from fastapi import Request
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

_AI_CREDITS_RESOURCE = "ai_credits"

# Cache window for the fail-open path (4xx from Django, e.g. expired token).
# Short enough that a fixed-up token recovers quickly; long enough to keep a
# misconfigured client off Django's neck during an auth-failure storm.
_FAIL_OPEN_CACHE_TTL_SECONDS = 5


@dataclass
class QuotaResourceStatus:
    limited: bool


def _redis_key(resource_key: str, team_id: int) -> str:
    return f"quota:{resource_key}:team:{team_id}"


async def resolve_quota_status(request: Request, team_id: int | None) -> QuotaResourceStatus:
    """Resolve the team's AI credits quota state, falling open on errors."""
    if team_id is None:
        return QuotaResourceStatus(limited=False)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return QuotaResourceStatus(limited=False)

    quota_resolver: QuotaResolver = request.app.state.quota_resolver
    try:
        return await quota_resolver.get_ai_credits_status(team_id=team_id, auth_header=auth_header)
    except Exception:
        logger.warning("quota_resolve_failed", team_id=team_id)
        return QuotaResourceStatus(limited=False)


class QuotaResolver:
    """Fetches team quota state from Django, caches per team."""

    def __init__(self, redis: Redis[bytes] | None, http_client: httpx.AsyncClient):
        self._redis = redis
        self._http = http_client
        self._cache_ttl = get_settings().quota_cache_ttl

    async def get_ai_credits_status(self, team_id: int, auth_header: str) -> QuotaResourceStatus:
        return await self._get_resource_status(_AI_CREDITS_RESOURCE, team_id, auth_header)

    async def _get_resource_status(self, resource_key: str, team_id: int, auth_header: str) -> QuotaResourceStatus:
        cached = await self._get_cached(resource_key, team_id)
        if cached is not None:
            return cached

        try:
            status, ttl = await self._fetch(resource_key, team_id, auth_header)
        except Exception:
            logger.warning("quota_fetch_failed", resource=resource_key, team_id=team_id, exc_info=True)
            return QuotaResourceStatus(limited=False)

        await self._set_cached(resource_key, team_id, status, ttl)
        return status

    async def _fetch(self, resource_key: str, team_id: int, auth_header: str) -> tuple[QuotaResourceStatus, int]:
        """Return the resource status and the TTL the caller should cache it for.

        4xx responses are treated as "not limited" and cached briefly so a hot
        loop with a broken token can't hammer Django.
        """
        settings = get_settings()
        if not settings.posthog_api_base_url:
            return QuotaResourceStatus(limited=False), _FAIL_OPEN_CACHE_TTL_SECONDS

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/projects/{team_id}/quota_limits/"
        resp = await self._http.get(
            url,
            headers={"Authorization": auth_header},
            timeout=2.0,
        )
        if resp.status_code >= 400:
            return QuotaResourceStatus(limited=False), _FAIL_OPEN_CACHE_TTL_SECONDS

        data = resp.json()
        resource = (data.get("limited") or {}).get(resource_key) or {}
        return QuotaResourceStatus(limited=bool(resource.get("limited"))), self._cache_ttl

    async def _get_cached(self, resource_key: str, team_id: int) -> QuotaResourceStatus | None:
        if not self._redis:
            return None
        try:
            val = await self._redis.get(_redis_key(resource_key, team_id))
            if val is None:
                return None
            payload = json.loads(val.decode())
            return QuotaResourceStatus(limited=bool(payload.get("limited")))
        except Exception:
            logger.debug("quota_cache_read_failed", resource=resource_key, team_id=team_id)
            return None

    async def _set_cached(self, resource_key: str, team_id: int, status: QuotaResourceStatus, ttl: int) -> None:
        if not self._redis:
            return
        try:
            payload = json.dumps({"limited": status.limited})
            await self._redis.set(_redis_key(resource_key, team_id), payload, ex=ttl)
        except Exception:
            logger.debug("quota_cache_write_failed", resource=resource_key, team_id=team_id)
