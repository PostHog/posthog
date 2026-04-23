"""Resolves a user's PostHog Code plan via the PostHog API seats endpoint.

Calls ``GET /api/seats/me/?product_key=posthog_code`` on the PostHog API,
forwarding the user's auth token. The Django SeatViewSet handles billing
JWT construction and proxies to the billing service.

Results are cached in Redis to avoid hitting the API on every request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from llm_gateway.config import get_settings

if TYPE_CHECKING:
    import httpx
    from fastapi import Request
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

POSTHOG_CODE_PRODUCT = "posthog_code"
PLAN_CACHE_PREFIX = f"plan:{POSTHOG_CODE_PRODUCT}"
PRO_PLAN_PREFIXES = ("posthog-code-200", "posthog-code-pro-")


@dataclass
class BillingPeriod:
    current_period_start: str
    current_period_end: str
    interval: str


@dataclass
class PlanInfo:
    plan_key: str | None
    seat_created_at: str | None
    billing_period: BillingPeriod | None = None


def _redis_key(user_id: int) -> str:
    return f"{PLAN_CACHE_PREFIX}:{user_id}"


def is_pro_plan(plan_key: str | None) -> bool:
    if not plan_key:
        return False
    return any(plan_key.startswith(p) for p in PRO_PLAN_PREFIXES)


def get_billing_period_number(
    seat_created_at: str | None,
    period_days: int = 30,
    billing_period_start: str | None = None,
) -> int:
    anchor = billing_period_start or seat_created_at
    if not anchor:
        return 0
    try:
        created = datetime.fromisoformat(anchor)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        elapsed = datetime.now(tz=UTC) - created
        return max(0, elapsed.days // period_days)
    except (ValueError, TypeError):
        return 0


def _parse_billing_period(raw: object) -> BillingPeriod | None:
    if not isinstance(raw, dict):
        return None
    try:
        return BillingPeriod(
            current_period_start=raw["current_period_start"],
            current_period_end=raw["current_period_end"],
            interval=raw["interval"],
        )
    except (KeyError, TypeError):
        return None


async def resolve_plan_info(
    request: Request,
    user_id: int,
    product: str,
) -> PlanInfo:
    """Resolve plan info, returning safe defaults on failure."""
    if product != POSTHOG_CODE_PRODUCT:
        return PlanInfo(plan_key=None, seat_created_at=None)

    plan_resolver: PlanResolver = request.app.state.plan_resolver
    auth_header = request.headers.get("Authorization", "")
    try:
        return await plan_resolver.get_plan(
            user_id=user_id,
            auth_header=auth_header,
        )
    except Exception:
        logger.warning("plan_resolve_failed", user_id=user_id)
        return PlanInfo(plan_key=None, seat_created_at=None)


class PlanResolver:
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
            logger.debug("plan_cache_invalidate_failed", user_id=user_id)

    async def get_plan(self, user_id: int, auth_header: str) -> PlanInfo:
        """Return the user's plan info, using cache when available."""
        if not auth_header:
            return PlanInfo(plan_key=None, seat_created_at=None)

        cached = await self._get_cached(user_id)
        if cached is not None:
            return cached

        try:
            plan_key, seat_created_at, billing_period = await self._fetch_plan(auth_header)
        except Exception:
            logger.warning("seat_fetch_failed", user_id=user_id, exc_info=True)
            return PlanInfo(plan_key=None, seat_created_at=None)

        await self._set_cached(user_id, plan_key, seat_created_at, billing_period)
        return PlanInfo(
            plan_key=plan_key,
            seat_created_at=seat_created_at,
            billing_period=billing_period,
        )

    async def _get_cached(self, user_id: int) -> PlanInfo | None:
        if not self._redis:
            return None
        try:
            val = await self._redis.get(_redis_key(user_id))
            if val is not None:
                data = json.loads(val.decode())
                plan_key = data.get("plan_key") or None
                seat_created_at = data.get("created_at")
                billing_period = _parse_billing_period(data.get("billing_period"))
                return PlanInfo(
                    plan_key=plan_key,
                    seat_created_at=seat_created_at,
                    billing_period=billing_period,
                )
        except Exception:
            logger.debug("plan_cache_read_failed", user_id=user_id)
        return None

    async def _set_cached(
        self,
        user_id: int,
        plan_key: str | None,
        seat_created_at: str | None,
        billing_period: BillingPeriod | None = None,
    ) -> None:
        if not self._redis:
            return
        ttl = get_settings().plan_cache_ttl
        try:
            payload: dict[str, object] = {"plan_key": plan_key, "created_at": seat_created_at}
            if billing_period:
                payload["billing_period"] = {
                    "current_period_start": billing_period.current_period_start,
                    "current_period_end": billing_period.current_period_end,
                    "interval": billing_period.interval,
                }
            data = json.dumps(payload)
            await self._redis.set(_redis_key(user_id), data, ex=ttl)
        except Exception:
            logger.debug("plan_cache_write_failed", user_id=user_id)

    async def _fetch_plan(self, auth_header: str) -> tuple[str | None, str | None, BillingPeriod | None]:
        """Call the PostHog API seats endpoint to get the user's plan.

        Raises on transient HTTP failures so the caller can skip caching.
        Returns (None, None, None) for legitimate "no plan" states (404, no API URL).
        """
        settings = get_settings()
        if not settings.posthog_api_base_url:
            return None, None, None

        url = f"{settings.posthog_api_base_url.rstrip('/')}/api/seats/me/"
        resp = await self._http.get(
            url,
            params={"product_key": POSTHOG_CODE_PRODUCT},
            headers={"Authorization": auth_header},
            timeout=2.0,
        )
        if resp.status_code == 404:
            return None, None, None
        resp.raise_for_status()
        data = resp.json()
        billing_period = _parse_billing_period(data.get("billing_period"))
        return data.get("plan_key"), data.get("created_at"), billing_period
