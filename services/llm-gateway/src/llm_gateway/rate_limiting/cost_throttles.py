from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from llm_gateway.config import DEFAULT_USER_COST_LIMIT, get_settings
from llm_gateway.products.config import resolve_cost_key

if TYPE_CHECKING:
    from llm_gateway.config import UserCostLimit
from llm_gateway.rate_limiting.redis_limiter import CostRateLimiter
from llm_gateway.rate_limiting.throttles import (
    Throttle,
    ThrottleContext,
    ThrottleResult,
    get_rate_limit_multiplier,
    is_usage_unlimited,
)
from llm_gateway.services.plan_resolver import POSTHOG_CODE_PRODUCT

logger = structlog.get_logger(__name__)


@dataclass
class CostStatus:
    used_usd: float
    limit_usd: float
    remaining_usd: float
    resets_in_seconds: int
    exceeded: bool


class CostThrottle(Throttle):
    scope: str

    def __init__(self, redis: Redis[bytes] | None):
        self._redis = redis
        self._limiters: dict[str, CostRateLimiter] = {}

    def _get_multiplier(self, context: ThrottleContext) -> int:
        return get_rate_limit_multiplier(context.user)

    def _cost_key(self, context: ThrottleContext) -> str:
        """The budget this request meters against — usually its product, see `resolve_cost_key`."""
        return resolve_cost_key(context.product, context.user.scopes)

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
            # A zero limit never refills, so the window is only a back-off hint.
            return ThrottleResult.deny(
                detail=self._get_limit_exceeded_detail(),
                scope=self.scope,
                retry_after=window,
                retry_after_resets_limit=False,
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
            logger.error(
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
                used_usd=current,
                limit_usd=limit,
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
        mult = self._get_multiplier(context)
        base = f"cost:product:{self._cost_key(context)}"
        if mult == 1:
            return base
        return f"{base}:m{mult}"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        settings = get_settings()
        product_config = settings.product_cost_limits.get(self._cost_key(context))
        if product_config:
            base_limit = product_config.limit_usd
            window = product_config.window_seconds
        else:
            base_limit = 1000.0
            window = 86400
        mult = self._get_multiplier(context)
        return base_limit * mult, window

    async def get_status_for_product(self, product: str) -> CostStatus | None:
        """Return CostStatus for a product using the shared (multiplier = 1) pool.

        Intended for monitoring/gauges, not throttling decisions — throttling needs
        a full ThrottleContext to apply the rate-limit multiplier. Returns None when the
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
        mult = self._get_multiplier(context)
        base = f"cost:user:{self.scope}:{self._cost_key(context)}:{context.end_user_id}"
        if mult == 1:
            return base
        return f"{base}:m{mult}"

    def _get_config(self, context: ThrottleContext) -> UserCostLimit:
        cost_key = self._cost_key(context)
        config = get_settings().user_cost_limits.get(cost_key)
        if not config:
            if context.end_user_id and cost_key not in self._warned_products:
                self._warned_products.add(cost_key)
                logger.info(
                    "user_cost_limits_using_default",
                    product=cost_key,
                    message=f"No user_cost_limits config for product '{cost_key}' — using default limits",
                )
            return DEFAULT_USER_COST_LIMIT
        return config

    def _is_exempt(self, context: ThrottleContext) -> bool:
        """Whether this request meters against the posthog_code budget, which billable credits
        cover instead of a per-user cost limit.

        Keyed on the resolved cost key rather than the declared product, for the same reason
        `_cost_key` is: a Signals run holding an Array-app token declares `posthog_code`, and
        reading the declaration here would hand it this exemption and leave the interactive
        budget its spend is keyed to unenforced.
        """
        return self._cost_key(context) == POSTHOG_CODE_PRODUCT

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        if not context.end_user_id or self._is_exempt(context):
            return ThrottleResult.allow()
        if is_usage_unlimited(context.user):
            return ThrottleResult.allow()
        settings = get_settings()
        if settings.user_cost_limits_disabled:
            await super().allow_request(context)
            return ThrottleResult.allow()
        return await super().allow_request(context)

    async def get_status(self, context: ThrottleContext) -> CostStatus:
        if self._is_exempt(context) or is_usage_unlimited(context.user):
            # Staff have no per-user cap: report an effectively unlimited budget
            # so the usage endpoint computes 0% used and never flags the user as
            # rate limited. `float("inf")` never crosses the wire — only
            # `used_percent`/`exceeded` are serialized to the client.
            _, window = self._get_limit_and_window(context)
            return CostStatus(
                used_usd=0.0,
                limit_usd=float("inf"),
                remaining_usd=float("inf"),
                resets_in_seconds=window,
                exceeded=False,
            )
        return await super().get_status(context)

    async def record_cost(self, context: ThrottleContext, cost: float) -> None:
        if not context.end_user_id or self._is_exempt(context):
            return
        await super().record_cost(context, cost)


class SandboxTaskCostThrottle(CostThrottle):
    """Total spend ceiling for one sandbox run, keyed on the task its token was minted for.

    The product and per-user budgets are windowed, so a single conversation can spend a window's
    worth of budget before either notices — and a user-started agent run has no natural end, since
    the person can keep replying to it. This bounds the run itself. The key comes from the token
    row rather than from request attribution, which the sandbox writes and could vary per call.

    Opt-in: a cost key absent from `sandbox_task_cost_limits` has no ceiling, so this is inert for
    every product that hasn't configured one.
    """

    scope = "sandbox_task_cost"

    def _get_limit_exceeded_detail(self) -> str:
        return "This agent run reached its spend limit"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        if not context.sandbox_task_id:
            return ""
        # Deliberately not multiplied by the staff/team rate-limit multiplier: this is a
        # per-run circuit breaker, and an elevated fleet-wide multiplier shouldn't widen it.
        return f"cost:task:{context.sandbox_task_id}"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        config = get_settings().sandbox_task_cost_limits.get(self._cost_key(context))
        if config is None:
            return 0.0, 0
        return config.limit_usd, config.window_seconds

    def _is_configured(self, context: ThrottleContext) -> bool:
        return bool(context.sandbox_task_id) and self._cost_key(context) in get_settings().sandbox_task_cost_limits

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        if not self._is_configured(context) or get_settings().sandbox_task_cost_limits_disabled:
            return ThrottleResult.allow()
        return await super().allow_request(context)

    async def record_cost(self, context: ThrottleContext, cost: float) -> None:
        if not self._is_configured(context):
            return
        # Recorded even when enforcement is off, so a dark launch measures what it would block.
        await super().record_cost(context, cost)


class UserCostBurstThrottle(_UserCostThrottleBase):
    scope = "user_cost_burst"

    def _get_limit_exceeded_detail(self) -> str:
        return "User burst rate limit exceeded"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        config = self._get_config(context)
        mult = self._get_multiplier(context)
        return config.burst_limit_usd * mult, config.burst_window_seconds


class UserCostSustainedThrottle(_UserCostThrottleBase):
    scope = "user_cost_sustained"

    def _get_limit_exceeded_detail(self) -> str:
        return "User sustained rate limit exceeded"

    def _get_limit_and_window(self, context: ThrottleContext) -> tuple[float, int]:
        config = self._get_config(context)
        mult = self._get_multiplier(context)
        return config.sustained_limit_usd * mult, config.sustained_window_seconds
