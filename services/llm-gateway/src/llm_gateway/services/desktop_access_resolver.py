"""Resolves whether a user is entitled to PostHog Desktop.

Calls ``GET /api/code/invites/check-access/`` on the PostHog API, forwarding the
user's auth token. Django answers from ``has_tasks_access`` — the `tasks` feature
flag or a redeemed invite — so the gateway never has to reimplement (or drift
from) that rule, and never needs a read grant on the redemption table.

Mirrors :mod:`llm_gateway.services.plan_resolver`: same auth forwarding, same
Redis caching shape.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from llm_gateway.config import get_settings

if TYPE_CHECKING:
    import httpx
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

DESKTOP_ACCESS_CACHE_PREFIX = "desktop_access"


def _redis_key(user_id: int) -> str:
    return f"{DESKTOP_ACCESS_CACHE_PREFIX}:{user_id}"


class DesktopAccessResolver:
    def __init__(
        self,
        redis: Redis[bytes] | None,
        http_client: httpx.AsyncClient,
    ):
        self._redis = redis
        self._http = http_client

    async def invalidate(self, user_id: int) -> None:
        if not self._redis:
            return
        try:
            await self._redis.delete(_redis_key(user_id))
        except Exception:
            logger.debug("desktop_access_cache_invalidate_failed", user_id=user_id)

    async def has_access(self, user_id: int, auth_header: str) -> bool | None:
        """True/False when Django answered, None when the answer is unavailable.

        None is distinct from False on purpose: the caller fails open on it, so a
        Django or network outage degrades to today's behaviour rather than taking
        PostHog Desktop down for every entitled user. Only a definitive "no" from
        Django blocks a request.
        """
        if not auth_header:
            return None

        cached = await self._get_cached(user_id)
        if cached is not None:
            return cached

        try:
            allowed = await self._fetch_access(auth_header)
        except Exception:
            logger.warning("desktop_access_fetch_failed", user_id=user_id, exc_info=True)
            return None

        if allowed is None:
            return None

        await self._set_cached(user_id, allowed)
        return allowed

    async def _get_cached(self, user_id: int) -> bool | None:
        if not self._redis:
            return None
        try:
            val = await self._redis.get(_redis_key(user_id))
            if val is not None:
                data = json.loads(val.decode())
                has_access = data.get("has_access")
                if isinstance(has_access, bool):
                    return has_access
        except Exception:
            logger.debug("desktop_access_cache_read_failed", user_id=user_id)
        return None

    async def _set_cached(self, user_id: int, has_access: bool) -> None:
        if not self._redis:
            return
        settings = get_settings()
        # A revoked entitlement should stop spend quickly, while a granted one is
        # cheap to hold; a freshly invited user is unblocked by the shorter miss TTL.
        ttl = settings.desktop_access_cache_ttl if has_access else settings.desktop_access_denied_cache_ttl
        try:
            await self._redis.set(_redis_key(user_id), json.dumps({"has_access": has_access}), ex=ttl)
        except Exception:
            logger.debug("desktop_access_cache_write_failed", user_id=user_id)

    async def _fetch_access(self, auth_header: str) -> bool | None:
        """Ask Django whether this user may use PostHog Desktop.

        Raises on transient HTTP failures so the caller can skip caching. Returns
        None when the check cannot be made at all (no API URL configured), which
        the caller treats as "unknown" rather than "denied".
        """
        settings = get_settings()
        if not settings.posthog_api_base_url:
            return None

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/code/invites/check-access/"
        resp = await self._http.get(
            url,
            headers={"Authorization": auth_header},
            timeout=settings.desktop_access_request_timeout,
        )
        # 401/403 mean the token can't answer for itself, not that the user is
        # unentitled — auth already vouched for this caller, so don't deny on it.
        if resp.status_code in (401, 403):
            logger.warning("desktop_access_check_unauthorized", status_code=resp.status_code)
            return None
        resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, dict):
            return None
        has_access = data.get("has_access")
        return has_access if isinstance(has_access, bool) else None
