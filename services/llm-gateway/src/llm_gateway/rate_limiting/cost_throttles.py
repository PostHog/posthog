from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from llm_gateway.config import (
    DEFAULT_USER_COST_LIMIT,
    FREE_PLAN_COST_LIMIT,
    get_settings,
)

if TYPE_CHECKING:
    from llm_gateway.config import UserCostLimit
from llm_gateway.rate_limiting.redis_limiter import CostRateLimiter
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult, get_team_multiplier
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT, get_billing_period_number, is_pro_plan

logger = structlog.get_logger(__name__)


@dataclass
class CostStatus:
    used_usd: float
    limit_usd: float
    remaining_usd: float
    resets_in_seconds: int
    exceeded: bool


def _is_free_plan_throttled(context: ThrottleContext) -> bool:
    return (
        context.product == POSTHOG_CODE_PRODUCT
        and not is_pro_plan(context.plan_key)
        and context.seat_created_at is not None
    )


class CostThrottle(Throttle):
    scope: str

    def __init__(self, redis: Redis[bytes] | None):
        self._redis = redis
        self._limiters: dict[str, CostRateLimiter] = {}

    def _get_team_multiplier(self, context: ThrottleContext) -> int:
        return get_team_multiplier(context.user.team_id)

    @abstractmethod
    def _get_cache_key(self, context: ThrottleContext) -> str: ...

    @abstractmethod
    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]: ...

    def _get_limiter(self, context: ThrottleContext) -> CostRateLimiter:
        limit, window = self._get_limit_and_window(context)
        limiter_key = f"{self.scope}:{limit}:{window}"
        if limiter_key not in self._limiters:
            self._limiters[limiter_key] = CostRateLimiter(
                redis=self._redis,
                limit=limit,
                window_seconds=window,
            )
        return self._limiters[limiter_key]

    @abstractmethod
    def _get_limit_exceeded_detail(self) -> str: ...

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        limit, window = self._get_limit_and_window(context)
        if limit <= 0:
            return ThrottleResult.deny(
                detail=self._get_limit_exceeded_detail(),
                scope=self.scope,
                retry_after=window,
            )
        limiter = self._get_limiter(context)
        key = self._get_cache_key(context)

        current = await limiter.get_current(key)
        ttl = await limiter.get_ttl(key)
        logger.debug(
            "cost_throttle_check",
            scope=self.scope,
            key=key,
            current_cost=current,
            limit=limit,
            window_seconds=window,
            ttl_seconds=ttl,
            remaining=limit - current,
        )
        if current >= limit:
            retry_after = await limiter.get_ttl(key)
            logger.warning(
                "cost_throttle_exceeded",
                scope=self.scope,
                key=key,
                current_cost=current,
                limit=limit,
                retry_after=retry_after,
            )
            return ThrottleResult.deny(
                detail=self._get_limit_exceeded_detail(),
                scope=self.scope,
                retry_after=retry_after,
            )
        return ThrottleResult.allow()

    async def record_cost(self, context: ThrottleContext, cost: float) -> None:
        if cost <= 0:
            return
        limiter = self._get_limiter(context)
        key = self._get_cache_key(context)
        limit, window = self._get_limit_and_window(context)
        await limiter.incr(key, cost)
        new_total = await limiter.get_current(key)
        ttl = await limiter.get_ttl(key)
        logger.debug(
            "cost_throttle_recorded",
            scope=self.scope,
            key=key,
            cost=cost,
            new_total=new_total,
            limit=limit,
            window_seconds=window,
            ttl_seconds=ttl,
            remaining=limit - new_total,
        )

    async def get_status(self, context: ThrottleContext) -> CostStatus:
        limit, window = self._get_limit_and_window(context)
        if limit <= 0:
            return CostStatus(
                used_usd=0.0,
                limit_usd=0.0,
                remaining_usd=0.0,
                resets_in_seconds=window,
                exceeded=True,
            )
        limiter = self._get_limiter(context)
        key = self._get_cache_key(context)

        current = await limiter.get_current(key)
        ttl = await limiter.get_ttl(key)
        remaining = max(0.0, limit - current)

        return CostStatus(
            used_usd=current,
            limit_usd=limit,
            remaining_usd=remaining,
            resets_in_seconds=ttl,
            exceeded=current >= limit,
        )


class ProductCostThrottle(CostThrottle):
    scope = "product_cost"

    def _get_limit_exceeded_detail(self) -> str:
        return "Product rate limit exceeded"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        team_mult = self._get_team_multiplier(context)
        base = f"cost:product:{context.product}"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        settings = get_settings()
        product_config = settings.product_cost_limits.get(context.product)
        if product_config:
            base_limit = product_config.limit_usd
            window = product_config.window_seconds
        else:
            base_limit = 1000.0
            window = 86400
        team_mult = self._get_team_multiplier(context)
        return base_limit * team_mult, window

    async def get_status_for_product(self, product: str) -> CostStatus | None:
        """Return CostStatus for a product using the shared (team multiplier = 1) pool.

        Intended for monitoring/gauges, not throttling decisions — throttling needs
        a full ThrottleContext to apply team multipliers. Returns None when the
        product has no configured cost limit.
        """
        settings = get_settings()
        config = settings.product_cost_limits.get(product)
        if config is None:
            return None

        limit = config.limit_usd
        window = config.window_seconds
        limiter_key = f"{self.scope}:{limit}:{window}"
        if limiter_key not in self._limiters:
            self._limiters[limiter_key] = CostRateLimiter(
                redis=self._redis,
                limit=limit,
                window_seconds=window,
            )
        limiter = self._limiters[limiter_key]
        key = f"cost:product:{product}"

        current = await limiter.get_current(key)
        ttl = await limiter.get_ttl(key)
        return CostStatus(
            used_usd=current,
            limit_usd=limit,
            remaining_usd=max(0.0, limit - current),
            resets_in_seconds=ttl,
            exceeded=current >= limit,
        )


class _UserCostThrottleBase(CostThrottle):
    """Base for per-product user cost throttles (burst/sustained pattern).

    end_user_id is always the authenticated user's ID, set at context creation.

    If no end_user_id is set, user rate limiting is skipped.
    If a product is not in user_cost_limits config, default limits are used ($100/24h burst, $1000/30d sustained).
    """

    _warned_products: set[str] = set()

    def _get_cache_key(self, context: ThrottleContext) -> str:
        if not context.end_user_id:
            return ""
        team_mult = self._get_team_multiplier(context)
        base = f"cost:user:{self.scope}:{context.product}:{context.end_user_id}"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"

    def _get_config(self, context: ThrottleContext) -> UserCostLimit:
        if _is_free_plan_throttled(context):
            return FREE_PLAN_COST_LIMIT

        config = get_settings().user_cost_limits.get(context.product)
        if not config:
            if context.end_user_id and context.product not in self._warned_products:
                self._warned_products.add(context.product)
                logger.info(
                    "user_cost_limits_using_default",
                    product=context.product,
                    message=f"No user_cost_limits config for product '{context.product}' — using default limits",
                )
            return DEFAULT_USER_COST_LIMIT
        return config

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        if not context.end_user_id:
            return ThrottleResult.allow()
        settings = get_settings()
        if settings.user_cost_limits_disabled:
            await super().allow_request(context)
            return ThrottleResult.allow()
        return await super().allow_request(context)

    async def record_cost(self, context: ThrottleContext, cost: float) -> None:
        if not context.end_user_id:
            return
        await super().record_cost(context, cost)


class UserCostBurstThrottle(_UserCostThrottleBase):
    scope = "user_cost_burst"

    def _get_limit_exceeded_detail(self) -> str:
        return "User burst rate limit exceeded"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        config = self._get_config(context)
        team_mult = self._get_team_multiplier(context)
        return config.burst_limit_usd * team_mult, config.burst_window_seconds


class UserCostSustainedThrottle(_UserCostThrottleBase):
    scope = "user_cost_sustained"

    def _get_limit_exceeded_detail(self) -> str:
        return "User sustained rate limit exceeded"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        base_key = super()._get_cache_key(context)
        if not base_key:
            return base_key
        if context.product == POSTHOG_CODE_PRODUCT:
            period = get_billing_period_number(
                context.seat_created_at,
                get_settings().billing_period_days,
                billing_period_start=context.billing_period_start,
            )
            return f"{base_key}:period:{period}"
        return base_key

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        config = self._get_config(context)
        team_mult = self._get_team_multiplier(context)
        return config.sustained_limit_usd * team_mult, config.sustained_window_seconds
