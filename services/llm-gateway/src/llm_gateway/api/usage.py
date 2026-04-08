from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.dependencies import get_authenticated_user
from llm_gateway.rate_limiting.cost_throttles import CostStatus, UserCostBurstThrottle, UserCostSustainedThrottle
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.services.plan_resolver import PlanResolver, resolve_plan_info

usage_router = APIRouter(prefix="/v1/usage", tags=["Usage"])


class CostLimitStatus(BaseModel):
    used_usd: float
    limit_usd: float
    remaining_usd: float
    resets_in_seconds: int
    exceeded: bool


class UsageResponse(BaseModel):
    product: str
    user_id: int
    burst: CostLimitStatus
    sustained: CostLimitStatus
    is_rate_limited: bool


def _to_cost_limit_status(status: CostStatus) -> CostLimitStatus:
    return CostLimitStatus(
        used_usd=round(status.used_usd, 6),
        limit_usd=round(status.limit_usd, 2),
        remaining_usd=round(status.remaining_usd, 6),
        resets_in_seconds=status.resets_in_seconds,
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

    context = ThrottleContext(
        user=user,
        product=product,
        end_user_id=str(user.user_id),
        plan_key=plan_info.plan_key,
        in_trial_period=plan_info.in_trial_period,
        seat_created_at=plan_info.seat_created_at,
    )

    burst_status: CostLimitStatus | None = None
    sustained_status: CostLimitStatus | None = None

    for throttle in runner.throttles:
        if isinstance(throttle, UserCostBurstThrottle):
            burst_status = _to_cost_limit_status(await throttle.get_status(context))
        elif isinstance(throttle, UserCostSustainedThrottle):
            sustained_status = _to_cost_limit_status(await throttle.get_status(context))

    if burst_status is None:
        burst_status = CostLimitStatus(used_usd=0, limit_usd=0, remaining_usd=0, resets_in_seconds=0, exceeded=False)
    if sustained_status is None:
        sustained_status = CostLimitStatus(
            used_usd=0, limit_usd=0, remaining_usd=0, resets_in_seconds=0, exceeded=False
        )

    return UsageResponse(
        product=product,
        user_id=user.user_id,
        burst=burst_status,
        sustained=sustained_status,
        is_rate_limited=burst_status.exceeded or sustained_status.exceeded,
    )


@usage_router.post("/{product}/invalidate-plan-cache")
async def invalidate_plan_cache(
    product: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> dict[str, bool]:
    if product != "posthog_code":
        raise HTTPException(status_code=404, detail="Plan cache not available for this product")
    plan_resolver: PlanResolver = request.app.state.plan_resolver
    await plan_resolver.invalidate(user.user_id)
    return {"ok": True}
