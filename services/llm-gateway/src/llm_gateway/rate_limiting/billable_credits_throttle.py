from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from llm_gateway.products.config import get_product_config
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


# Mirror of ee/billing/quota_limiting.py:
#   QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY = "@posthog/quota-limits/"
#   QuotaResource.AI_CREDITS = "ai_credits"
_AI_CREDITS_LIMIT_KEY = "@posthog/quota-limits/ai_credits"


class BillableCreditThrottle(Throttle):
    """Gate billable-product LLM calls on the team's AI credits balance.

    Reads the same Redis sorted set Django populates via
    ee/billing/quota_limiting.add_limited_team_tokens. Members are team API
    tokens; scores are Unix timestamps marking when the limit expires.

    Fail-open when Redis is unavailable or the user's team API token isn't
    known — matches the rest of the throttle chain. Without this we'd close
    requests on infrastructure incidents that have nothing to do with billing.
    """

    scope = "billable_credits"

    def __init__(self, redis: Redis[bytes] | None, clock: Callable[[], float] | None = None):
        self._redis = redis
        self._now = clock or time.time
        if redis is None:
            logger.warning(
                "billable_credits_throttle_disabled_no_redis",
                reason="Redis client not configured; throttle is fail-open and will allow all billable calls.",
            )

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        config = get_product_config(context.product)
        if not (config and config.billable):
            return ThrottleResult.allow()

        if self._redis is None or context.user.team_api_token is None:
            return ThrottleResult.allow()

        score = await self._redis.zscore(_AI_CREDITS_LIMIT_KEY, context.user.team_api_token)
        if score is None or score <= self._now():
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=(
                "Your team has used its monthly PostHog AI credits. "
                "Top up at https://us.posthog.com/organization/billing to continue."
            ),
            scope=self.scope,
            retry_after=max(int(score - self._now()), 1),
        )
