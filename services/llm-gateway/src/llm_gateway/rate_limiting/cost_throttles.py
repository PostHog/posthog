from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from llm_gateway.config import DEFAULT_USER_COST_LIMIT, get_settings

if TYPE_CHECKING:
    from llm_gateway.config import UserCostLimit
from llm_gateway.rate_limiting.redis_limiter import CostRateLimiter
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult, get_team_multiplier

logger = structlog.get_logger(__name__)


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
        limiter = self._get_limiter(context)
        key = self._get_cache_key(context)
        limit, window = self._get_limit_and_window(context)

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


class _UserCostThrottleBase(CostThrottle):
    """Base for per-product user cost throttles (burst/sustained pattern).

    - OAuth: end_user_id is the token holder (set at context creation)
    - Personal API key: end_user_id is the 'user' param from the request (set in callback)

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

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        config = self._get_config(context)
        team_mult = self._get_team_multiplier(context)
        return config.sustained_limit_usd * team_mult, config.sustained_window_seconds
