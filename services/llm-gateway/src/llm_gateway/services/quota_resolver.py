"""Resolves a team's quota state via the PostHog API quota_limits endpoint.

Mirrors :mod:`llm_gateway.services.plan_resolver` — forwards the caller's
``Authorization`` header to ``GET /api/projects/{team_id}/quota_limits/`` and
caches the result per team-and-resource in the gateway's own Redis.

Transient upstream failures (network errors, 5xx) are retried within the
request with exponential backoff. 4xx responses or exhausted retries fall
open and briefly cache ``limited=False`` so a struggling Django isn't hit on
every subsequent request.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog

from llm_gateway.config import get_settings

if TYPE_CHECKING:
    from fastapi import Request
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

_AI_CREDITS_RESOURCE = "ai_credits"

# Cache window for the fail-open path (4xx from Django, or transient failure
# after retries are exhausted). Long enough to keep a misconfigured client off
# Django's neck during an auth-failure storm; short enough that a recovered
# upstream is consulted again within a minute.
_FAIL_OPEN_CACHE_TTL_SECONDS = 60

# Exponential backoff between within-request retries on transient failures.
# The first attempt fires immediately; each subsequent retry waits
# ``MULTIPLIER * 2**n`` seconds, doubling the gap each step. Tune the
# multiplier to widen or tighten the overall spacing without touching the
# formula.
_MAX_RETRIES = 3
_RETRY_BACKOFF_MULTIPLIER_SECONDS = 5
_RETRY_DELAYS_SECONDS: tuple[float, ...] = (
    0,
    *(_RETRY_BACKOFF_MULTIPLIER_SECONDS * 2**i for i in range(_MAX_RETRIES)),
)


@dataclass
class QuotaResourceStatus:
    limited: bool


class _TransientUpstreamError(Exception):
    """Retryable failure: a 5xx response or a network-level error."""


def _redis_key(resource_key: str, team_id: int) -> str:
    return f"quota:{resource_key}:team:{team_id}"


async def resolve_quota_status(
    request: Request, team_id: int | None, resource_key: str = _AI_CREDITS_RESOURCE
) -> QuotaResourceStatus:
    """Resolve the team's quota state for ``resource_key``, falling open on errors."""
    if team_id is None:
        return QuotaResourceStatus(limited=False)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return QuotaResourceStatus(limited=False)

    quota_resolver: QuotaResolver = request.app.state.quota_resolver
    try:
        return await quota_resolver.get_resource_status(
            resource_key=resource_key, team_id=team_id, auth_header=auth_header
        )
    except Exception:
        logger.warning("quota_resolve_failed", team_id=team_id, resource=resource_key)
        return QuotaResourceStatus(limited=False)


class QuotaResolver:
    """Fetches team quota state from Django, caches per team."""

    def __init__(self, redis: Redis[bytes] | None, http_client: httpx.AsyncClient):
        self._redis = redis
        self._http = http_client
        self._cache_ttl = get_settings().quota_cache_ttl

    async def get_resource_status(self, resource_key: str, team_id: int, auth_header: str) -> QuotaResourceStatus:
        cached = await self._get_cached(resource_key, team_id)
        if cached is not None:
            return cached

        try:
            status, ttl = await self._fetch_with_retry(resource_key, team_id, auth_header)
        except Exception:
            logger.warning("quota_fetch_failed", resource=resource_key, team_id=team_id, exc_info=True)
            status, ttl = QuotaResourceStatus(limited=False), _FAIL_OPEN_CACHE_TTL_SECONDS

        await self._set_cached(resource_key, team_id, status, ttl)
        return status

    async def _fetch_with_retry(
        self, resource_key: str, team_id: int, auth_header: str
    ) -> tuple[QuotaResourceStatus, int]:
        """Try the upstream up to ``len(_RETRY_DELAYS_SECONDS)`` times.

        Network errors and 5xx responses are retried with growing waits between
        attempts. 4xx and successful responses return immediately from
        :meth:`_fetch`. If every attempt raises a transient error the last
        exception is re-raised for the caller to fail open.
        """
        last_exc: Exception | None = None
        for delay in _RETRY_DELAYS_SECONDS:
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._fetch(resource_key, team_id, auth_header)
            except _TransientUpstreamError as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    async def _fetch(self, resource_key: str, team_id: int, auth_header: str) -> tuple[QuotaResourceStatus, int]:
        """One attempt against Django. Raises :class:`_TransientUpstreamError` on retryable failures."""
        settings = get_settings()
        if not settings.posthog_api_base_url:
            return QuotaResourceStatus(limited=False), _FAIL_OPEN_CACHE_TTL_SECONDS

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/projects/{team_id}/quota_limits/"
        try:
            resp = await self._http.get(url, headers={"Authorization": auth_header}, timeout=2.0)
        except httpx.RequestError as exc:
            raise _TransientUpstreamError(str(exc)) from exc

        if resp.status_code >= 500:
            raise _TransientUpstreamError(f"quota_limits returned {resp.status_code}")
        if resp.status_code >= 400:
            # 4xx is permanent for the lifetime of this request — bad token,
            # missing team, scope mismatch. Fail open briefly so a hot loop
            # with a broken token doesn't hammer Django.
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
