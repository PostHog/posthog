from __future__ import annotations

import structlog
from redis.asyncio import Redis

from llm_gateway.metrics.prometheus import REDIS_FALLBACK
from llm_gateway.rate_limiting.token_bucket import TokenBucketLimiter

logger = structlog.get_logger(__name__)


class RateLimiter:
    """
    Redis-backed rate limiter with local fallback.

    Implements dual-limit rate limiting (burst and sustained) using fixed window
    counters with expiration in Redis. Falls back to in-memory token bucket
    limiters if Redis is unavailable.
    """

    def __init__(
        self,
        redis: Redis[bytes] | None,
        burst_limit: int,
        burst_window: int,
        sustained_limit: int,
        sustained_window: int,
    ):
        self.redis = redis
        self.burst_limit = burst_limit
        self.burst_window = burst_window
        self.sustained_limit = sustained_limit
        self.sustained_window = sustained_window

        self._local_burst = TokenBucketLimiter(
            rate=burst_limit / burst_window,
            capacity=float(burst_limit),
        )
        self._local_sustained = TokenBucketLimiter(
            rate=sustained_limit / sustained_window,
            capacity=float(sustained_limit),
        )

    async def _check_redis_limit(self, key: str, limit: int, window: int) -> bool:
        """Check rate limit using Redis sliding window counter."""
        if self.redis is None:
            return True

        current: int = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, window)
        return current <= limit

    def _check_local_limit(self, key: str) -> tuple[bool, str | None]:
        """Check rate limit using local token bucket. Returns (allowed, scope_if_exceeded)."""
        if not self._local_burst.consume(key):
            return False, "burst"
        if not self._local_sustained.consume(key):
            return False, "sustained"
        return True, None

    async def check(self, user_id: int) -> tuple[bool, str | None]:
        """
        Check if request is allowed. Returns (allowed, exceeded_scope).
        Always checks local first, then Redis for global enforcement.
        """
        key = str(user_id)

        allowed, scope = self._check_local_limit(key)
        if not allowed:
            return False, scope

        if self.redis is None:
            return True, None

        try:
            burst_key = f"ratelimit:burst:{key}"
            if not await self._check_redis_limit(burst_key, self.burst_limit, self.burst_window):
                return False, "burst"

            sustained_key = f"ratelimit:sustained:{key}"
            if not await self._check_redis_limit(sustained_key, self.sustained_limit, self.sustained_window):
                return False, "sustained"

            return True, None
        except Exception:
            logger.exception("redis_rate_limit_check_failed", user_id=user_id)
            REDIS_FALLBACK.inc()
            return True, None
