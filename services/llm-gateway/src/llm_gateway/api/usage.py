from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.dependencies import get_authenticated_user
from llm_gateway.rate_limiting.cost_throttles import CostStatus, UserCostBurstThrottle, UserCostSustainedThrottle
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT, PlanResolver, resolve_plan_info

usage_router = APIRouter(prefix="/v1/usage", tags=["Usage"])


class CostLimitStatus(BaseModel):
    used_percent: float
    resets_in_seconds: int
    # Absolute UTC reset timestamp. Prefer this over resets_in_seconds — the
    # rolling Redis window makes resets_in_seconds drift between polls.
    reset_at: datetime
    exceeded: bool


class UsageResponse(BaseModel):
    product: str
    user_id: int
    burst: CostLimitStatus
    sustained: CostLimitStatus
    is_rate_limited: bool
    billing_period_end: datetime | None = None


def _to_cost_limit_status(status: CostStatus, now: datetime | None = None) -> CostLimitStatus:
    if status.limit_usd > 0:
        used_percent = min(100.0, (status.used_usd / status.limit_usd) * 100)
    else:
        used_percent = 100.0
    anchor = now or datetime.now(tz=UTC)
    return CostLimitStatus(
        used_percent=round(used_percent, 1),
        resets_in_seconds=status.resets_in_seconds,
        reset_at=anchor + timedelta(seconds=status.resets_in_seconds),
        exceeded=status.exceeded,
    )


@usage_router.get("/{product}")
async def get_usage(
    product: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> UsageResponse:
    runner: ThrottleRunner = request.app.state.throttle_runner
    plan_info = await resolve_plan_info(request, user.user_id, product)
    now = datetime.now(tz=UTC)

    context = ThrottleContext(
        user=user,
        product=product,
        end_user_id=str(user.user_id),
        plan_key=plan_info.plan_key,
        seat_created_at=plan_info.seat_created_at,
        billing_period_start=plan_info.billing_period.current_period_start if plan_info.billing_period else None,
    )

    burst_status: CostLimitStatus | None = None
    sustained_status: CostLimitStatus | None = None

    for throttle in runner.throttles:
        if isinstance(throttle, UserCostBurstThrottle):
            burst_status = _to_cost_limit_status(await throttle.get_status(context), now=now)
        elif isinstance(throttle, UserCostSustainedThrottle):
            sustained_status = _to_cost_limit_status(await throttle.get_status(context), now=now)

    empty = CostStatus(used_usd=0, limit_usd=0, remaining_usd=0, resets_in_seconds=0, exceeded=False)
    if burst_status is None:
        burst_status = _to_cost_limit_status(empty, now=now)
    if sustained_status is None:
        sustained_status = _to_cost_limit_status(empty, now=now)

    billing_period_end: datetime | None = None
    if plan_info.billing_period:
        try:
            billing_period_end = datetime.fromisoformat(plan_info.billing_period.current_period_end)
        except (ValueError, TypeError):
            billing_period_end = None

    return UsageResponse(
        product=product,
        user_id=user.user_id,
        burst=burst_status,
        sustained=sustained_status,
        is_rate_limited=burst_status.exceeded or sustained_status.exceeded,
        billing_period_end=billing_period_end,
    )


@usage_router.post("/{product}/invalidate-plan-cache")
async def invalidate_plan_cache(
    product: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> dict[str, bool]:
    if product != POSTHOG_CODE_PRODUCT:
        raise HTTPException(status_code=404, detail="Plan cache not available for this product")
    plan_resolver: PlanResolver = request.app.state.plan_resolver
    await plan_resolver.invalidate(user.user_id)
    return {"ok": True}
