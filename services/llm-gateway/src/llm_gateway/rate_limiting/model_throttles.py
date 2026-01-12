from __future__ import annotations

from abc import abstractmethod
from typing import Final

from cachetools import TTLCache
from redis.asyncio import Redis

from llm_gateway.rate_limiting.redis_limiter import TokenRateLimiter
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

# Explicit limits per model family (tokens per minute)
# Unknown models default to expensive tier
# NOTE: Order matters! More specific keys must come before less specific ones
# (e.g., "gpt-4o-mini" before "gpt-4o")
MODEL_TOKEN_LIMITS: Final[dict[str, dict[str, int]]] = {
    # Anthropic models
    "claude-3-5-haiku": {"input_tpm": 4_000_000, "output_tpm": 800_000},
    "claude-3-5-sonnet": {"input_tpm": 2_000_000, "output_tpm": 400_000},
    "claude-3-opus": {"input_tpm": 2_000_000, "output_tpm": 400_000},
    "claude-sonnet-4": {"input_tpm": 2_000_000, "output_tpm": 400_000},
    "claude-opus-4": {"input_tpm": 2_000_000, "output_tpm": 400_000},
    # OpenAI models (more specific first)
    "gpt-4o-mini": {"input_tpm": 4_000_000, "output_tpm": 800_000},
    "gpt-4-turbo": {"input_tpm": 2_000_000, "output_tpm": 400_000},
    "gpt-4o": {"input_tpm": 2_000_000, "output_tpm": 400_000},
    # Default for unknown models (assume expensive)
    "default": {"input_tpm": 500_000, "output_tpm": 100_000},
}


def get_model_limits(model: str) -> dict[str, int]:
    """Get limits for model, defaulting to expensive tier for unknown models."""
    model_lower = model.lower()
    for model_key, limits in MODEL_TOKEN_LIMITS.items():
        if model_key != "default" and model_key in model_lower:
            return limits
    return MODEL_TOKEN_LIMITS["default"]


class TokenThrottle(Throttle):
    """Base class for token-based throttles with Redis fallback."""

    scope: str
    limit_key: str  # "input_tpm" or "output_tpm"
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
                window_seconds=60,
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

    limit_key = "input_tpm"

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

    limit_key = "output_tpm"
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
        if request_id not in self._reservations:
            return
        model, reserved, cache_key = self._reservations.pop(request_id)
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
