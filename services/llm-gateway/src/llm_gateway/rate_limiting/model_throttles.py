from __future__ import annotations

from abc import abstractmethod
from typing import Literal

from cachetools import TTLCache
from redis.asyncio import Redis

from llm_gateway.rate_limiting.model_cost_service import get_model_limits
from llm_gateway.rate_limiting.redis_limiter import TokenRateLimiter
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

LimitKey = Literal["input_tph", "output_tph"]


class TokenThrottle(Throttle):
    """Base class for token-based throttles with Redis fallback."""

    scope: str
    limit_key: LimitKey
    limit_multiplier: int = 1  # Override in subclass for global throttles (e.g., 10)

    def __init__(self, redis: Redis[bytes] | None):
        self._redis = redis
        self._limiters: dict[str, TokenRateLimiter] = {}

    def _get_limiter(self, model: str) -> TokenRateLimiter:
        if model not in self._limiters:
            limits = get_model_limits(model)
            limit = limits[self.limit_key] * self.limit_multiplier
            self._limiters[model] = TokenRateLimiter(
                redis=self._redis,
                limit=limit,
                window_seconds=3600,
            )
        return self._limiters[model]

    @abstractmethod
    def _get_cache_key(self, context: ThrottleContext) -> str:
        """Return the cache key for rate limiting."""
        ...

    @abstractmethod
    def _get_tokens(self, context: ThrottleContext) -> int | None:
        """Return the number of tokens to consume."""
        ...


class InputTokenThrottle(TokenThrottle):
    """Base for input token throttles."""

    limit_key = "input_tph"

    def _get_tokens(self, context: ThrottleContext) -> int | None:
        return context.input_tokens

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        tokens = self._get_tokens(context)
        if context.model is None or tokens is None:
            return ThrottleResult.allow()

        limiter = self._get_limiter(context.model)
        key = self._get_cache_key(context)

        if await limiter.consume(key, tokens):
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=f"Input token rate limit exceeded for model {context.model}",
            scope=self.scope,
        )


class OutputTokenThrottle(TokenThrottle):
    """Base for output token throttles with reservation support."""

    limit_key = "output_tph"
    RESERVATION_TTL_SECONDS = 300  # 5 minutes - reservations expire if response never completes
    RESERVATION_MAX_SIZE = 10_000  # Max concurrent requests tracked

    def __init__(self, redis: Redis[bytes] | None):
        super().__init__(redis)
        # TTLCache auto-expires entries after TTL, preventing memory leaks from abandoned requests
        self._reservations: TTLCache[str, tuple[str, int, str]] = TTLCache(
            maxsize=self.RESERVATION_MAX_SIZE, ttl=self.RESERVATION_TTL_SECONDS
        )

    def _get_tokens(self, context: ThrottleContext) -> int | None:
        return context.max_output_tokens

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        tokens = self._get_tokens(context)
        if context.model is None or tokens is None:
            return ThrottleResult.allow()

        limiter = self._get_limiter(context.model)
        key = self._get_cache_key(context)

        if await limiter.consume(key, tokens):
            if context.request_id:
                self._reservations[context.request_id] = (context.model, tokens, key)
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=f"Output token rate limit exceeded for model {context.model}",
            scope=self.scope,
        )

    async def adjust_after_response(self, request_id: str, actual_output_tokens: int) -> None:
        try:
            model, reserved, cache_key = self._reservations.pop(request_id)
        except KeyError:  # if the reservation is missing, just return, and leave the max tokens consumed
            return
        unused = reserved - actual_output_tokens
        if unused > 0:
            limiter = self._get_limiter(model)
            await limiter.release(cache_key, unused)


class GlobalModelInputTokenThrottle(InputTokenThrottle):
    scope = "global_model_input_tokens"
    limit_multiplier = 10

    def _get_cache_key(self, context: ThrottleContext) -> str:
        return f"global:model:{context.model}:input"


class UserModelInputTokenThrottle(InputTokenThrottle):
    scope = "user_model_input_tokens"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        return f"user:{context.user.user_id}:model:{context.model}:input"


class GlobalModelOutputTokenThrottle(OutputTokenThrottle):
    scope = "global_model_output_tokens"
    limit_multiplier = 10

    def _get_cache_key(self, context: ThrottleContext) -> str:
        return f"global:model:{context.model}:output"


class UserModelOutputTokenThrottle(OutputTokenThrottle):
    scope = "user_model_output_tokens"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        return f"user:{context.user.user_id}:model:{context.model}:output"
