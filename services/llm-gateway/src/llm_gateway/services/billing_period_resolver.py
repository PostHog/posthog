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


@dataclass(frozen=True, kw_only=True)
class OrganizationBillingPeriod:
    current_period_start: str
    current_period_end: str


def _redis_key(team_id: int) -> str:
    return f"billing_period:team:{team_id}"


class BillingPeriodResolver:
    def __init__(self, redis: Redis | None, http_client: httpx.AsyncClient):
        self._redis = redis
        self._http = http_client
        self._cache_ttl = get_settings().quota_cache_ttl

    async def get_period(self, team_id: int, auth_header: str) -> OrganizationBillingPeriod | None:
        cache_hit, cached = await self._get_cached(team_id)
        if cache_hit:
            return cached

        settings = get_settings()
        if not settings.posthog_api_base_url:
            return None

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/billing/period/"
        try:
            response = await self._http.get(
                url,
                headers={"Authorization": auth_header},
                params={"team_id": team_id},
                timeout=2.0,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Billing period response must be an object")
        except (httpx.HTTPError, ValueError):
            logger.warning("billing_period_fetch_failed", team_id=team_id, exc_info=True)
            return None

        start = data.get("current_period_start")
        end = data.get("current_period_end")
        if not isinstance(start, str) or not isinstance(end, str):
            await self._set_cached(team_id, None)
            return None

        period = OrganizationBillingPeriod(current_period_start=start, current_period_end=end)
        await self._set_cached(team_id, period)
        return period

    async def _get_cached(self, team_id: int) -> tuple[bool, OrganizationBillingPeriod | None]:
        if not self._redis:
            return False, None
        try:
            value = await self._redis.get(_redis_key(team_id))
            if value is None:
                return False, None
            data = json.loads(value.decode())
            start = data.get("current_period_start")
            end = data.get("current_period_end")
            if isinstance(start, str) and isinstance(end, str):
                return True, OrganizationBillingPeriod(current_period_start=start, current_period_end=end)
            if start is None and end is None:
                return True, None
        except Exception:
            logger.debug("billing_period_cache_read_failed", team_id=team_id)
        return False, None

    async def _set_cached(self, team_id: int, period: OrganizationBillingPeriod | None) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(
                _redis_key(team_id),
                json.dumps(
                    {
                        "current_period_start": period.current_period_start if period else None,
                        "current_period_end": period.current_period_end if period else None,
                    }
                ),
                ex=self._cache_ttl,
            )
        except Exception:
            logger.debug("billing_period_cache_write_failed", team_id=team_id)


async def resolve_billing_period(request: Request, team_id: int | None) -> OrganizationBillingPeriod | None:
    if team_id is None:
        return None

    auth_header = upstream_auth_header(request)
    if not auth_header:
        return None

    resolver: BillingPeriodResolver = request.app.state.billing_period_resolver
    try:
        return await resolver.get_period(team_id=team_id, auth_header=auth_header)
    except Exception:
        logger.warning("billing_period_resolution_failed", team_id=team_id, exc_info=True)
        return None
