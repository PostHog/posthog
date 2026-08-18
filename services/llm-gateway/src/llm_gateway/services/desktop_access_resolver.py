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

    async def has_access(self, user_id: int, auth_header: str) -> bool:
        cached = await self._get_cached(user_id)
        if cached is not None:
            return cached

        try:
            allowed = await self._fetch_access(auth_header)
        except Exception:
            logger.warning("desktop_access_fetch_failed", user_id=user_id, exc_info=True)
            allowed = False

        settings = get_settings()
        ttl = settings.desktop_access_cache_ttl if allowed else settings.desktop_access_denied_cache_ttl
        await self._set_cached(user_id, allowed, ttl)
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

    async def _set_cached(self, user_id: int, has_access: bool, ttl: int) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(_redis_key(user_id), json.dumps({"has_access": has_access}), ex=ttl)
        except Exception:
            logger.debug("desktop_access_cache_write_failed", user_id=user_id)

    async def _fetch_access(self, auth_header: str) -> bool:
        settings = get_settings()
        if not settings.posthog_api_base_url:
            logger.warning("desktop_access_check_unconfigured")
            return False

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/code/invites/check-access/"
        resp = await self._http.get(
            url,
            headers={"Authorization": auth_header},
            timeout=settings.desktop_access_request_timeout,
        )
        if resp.status_code != 200:
            logger.warning("desktop_access_check_failed", status_code=resp.status_code)
            return False

        data = resp.json()
        has_access = data.get("has_access") if isinstance(data, dict) else None
        if not isinstance(has_access, bool):
            logger.warning("desktop_access_check_malformed_response")
            return False
        return has_access
