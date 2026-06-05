"""Staff admin endpoints for inspecting and resetting a user's PostHog Code
usage / rate-limit counters.

These are called server-to-server from the PostHog Django admin (which gates
access to staff users). Authentication is a shared secret (`LLM_GATEWAY_ADMIN_SECRET`
on Django, `admin_secret` here) sent in the `x-llm-gateway-admin-secret` header.
When the secret is not configured the endpoints are disabled (404), so they can
never be hit unauthenticated.

Resetting works on the live, per-user, per-product cost counters by deleting the
matching Redis keys (see rate_limiting/usage_reset.py). The product-wide pool and
the dormant request-rate counters are opt-in.
"""

from __future__ import annotations

import hmac

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from redis.asyncio import Redis

from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.usage_reset import (
    cost_patterns,
    product_patterns,
    request_patterns,
    reset_keys,
    scan_cost_usage,
)
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT

logger = structlog.get_logger(__name__)

admin_router = APIRouter(prefix="/v1/admin", tags=["Admin"])

_ADMIN_SECRET_HEADER = "x-llm-gateway-admin-secret"


async def require_admin_secret(request: Request) -> None:
    """Gate admin endpoints on the shared secret. 404 when disabled (so the
    surface is invisible without the secret), 401 on mismatch."""
    configured = get_settings().admin_secret
    if not configured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    provided = request.headers.get(_ADMIN_SECRET_HEADER, "")
    if not hmac.compare_digest(provided, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin secret")


AdminAuth = Depends(require_admin_secret)


def _get_redis(request: Request) -> Redis:
    redis: Redis | None = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis not configured")
    return redis


class CostCounter(BaseModel):
    key: str
    scope: str
    used_usd: float
    resets_in_seconds: int
    base_limit_usd: float


class UsageResponse(BaseModel):
    user_id: str
    product: str
    counters: list[CostCounter]


class ResetRequest(BaseModel):
    # cost is the live, per-user, per-product limit; default on. request-rate is
    # dormant and product_total touches the shared pool, so both are opt-in.
    cost: bool = True
    request: bool = False
    product_total: bool = False
    dry_run: bool = False


class ResetResponse(BaseModel):
    user_id: str
    dry_run: bool
    cost_keys: int
    request_keys: int
    product_total_keys: int
    total_keys: int


@admin_router.get("/usage/{user_id}", dependencies=[AdminAuth])
async def get_user_usage(user_id: str, request: Request) -> UsageResponse:
    """Read the user's live posthog_code cost counters (used $, reset time)."""
    redis = _get_redis(request)
    usages = await scan_cost_usage(redis, user_id)
    return UsageResponse(
        user_id=user_id,
        product=POSTHOG_CODE_PRODUCT,
        counters=[CostCounter(**u.as_dict()) for u in usages],  # type: ignore[arg-type]
    )


@admin_router.post("/reset/{user_id}", dependencies=[AdminAuth])
async def reset_user_usage(user_id: str, request: Request, body: ResetRequest) -> ResetResponse:
    """Reset a single user's posthog_code limits. cost is reset by default;
    request-rate and the product-wide pool are opt-in via the body flags."""
    redis = _get_redis(request)

    cost_keys = 0
    request_keys = 0
    product_total_keys = 0

    if body.cost:
        cost_keys = await reset_keys(redis, cost_patterns(user_id), dry_run=body.dry_run)
    if body.request:
        request_keys = await reset_keys(redis, request_patterns(user_id), dry_run=body.dry_run)
    if body.product_total:
        product_total_keys = await reset_keys(redis, product_patterns(), dry_run=body.dry_run)

    total = cost_keys + request_keys + product_total_keys
    logger.info(
        "admin_reset_usage",
        user_id=user_id,
        dry_run=body.dry_run,
        cost=body.cost,
        request=body.request,
        product_total=body.product_total,
        total_keys=total,
    )
    return ResetResponse(
        user_id=user_id,
        dry_run=body.dry_run,
        cost_keys=cost_keys,
        request_keys=request_keys,
        product_total_keys=product_total_keys,
        total_keys=total,
    )
