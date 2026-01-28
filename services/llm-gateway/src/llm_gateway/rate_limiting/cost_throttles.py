from __future__ import annotations

from abc import abstractmethod

import structlog
from redis.asyncio import Redis

from llm_gateway.config import get_settings
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
            base_limit = 20.0
            window = 3600
        team_mult = self._get_team_multiplier(context)
        return base_limit * team_mult, window


class UserCostThrottle(CostThrottle):
    """Rate limit by end_user_id.

    - OAuth: end_user_id is the token holder (set at context creation)
    - Personal API key: end_user_id is the 'user' param from the request (set in callback)

    If no end_user_id is set, user rate limiting is skipped.
    """

    scope = "user_cost"

    def _get_limit_exceeded_detail(self) -> str:
        return "User rate limit exceeded"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        if not context.end_user_id:
            return ""
        team_mult = self._get_team_multiplier(context)
        base = f"cost:user:{context.end_user_id}"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        settings = get_settings()
        base_limit = settings.default_user_cost_limit_usd
        window = settings.default_user_cost_window_seconds
        team_mult = self._get_team_multiplier(context)
        return base_limit * team_mult, window

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
