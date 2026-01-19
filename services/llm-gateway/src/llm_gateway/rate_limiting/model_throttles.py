from __future__ import annotations

from abc import abstractmethod
from typing import Literal

import structlog
from redis.asyncio import Redis

from llm_gateway.rate_limiting.model_cost_service import get_model_limits
from llm_gateway.rate_limiting.redis_limiter import TokenRateLimiter
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult, get_team_multiplier

logger = structlog.get_logger(__name__)

LimitKey = Literal["input_tph", "output_tph"]


class TokenThrottle(Throttle):
    """Base class for token-based throttles with Redis fallback."""

    scope: str
    limit_key: LimitKey
    limit_multiplier: int = 1  # Override in subclass for global throttles (e.g., 10)
    token_type: str = "Token"  # Override: "Input" or "Output"
    window_seconds: int = 3600

    def __init__(self, redis: Redis[bytes] | None):
        self._redis = redis
        self._limiters: dict[str, TokenRateLimiter] = {}

    def _get_limiter_key(self, model: str, team_multiplier: int) -> str:
        if team_multiplier == 1:
            return model
        return f"{model}:tm{team_multiplier}"

    def _get_limiter(self, model: str, team_multiplier: int = 1) -> TokenRateLimiter:
        limiter_key = self._get_limiter_key(model, team_multiplier)
        if limiter_key not in self._limiters:
            limits = get_model_limits(model)
            base_limit = limits[self.limit_key] * self.limit_multiplier
            limit = base_limit * team_multiplier
            if team_multiplier > 1:
                logger.info(
                    "team_rate_limit_multiplier_applied",
                    model=model,
                    throttle_scope=self.scope,
                    base_limit=base_limit,
                    team_multiplier=team_multiplier,
                    effective_limit=limit,
                )
            self._limiters[limiter_key] = TokenRateLimiter(
                redis=self._redis,
                limit=limit,
                window_seconds=self.window_seconds,
            )
        return self._limiters[limiter_key]

    def _get_team_multiplier(self, context: ThrottleContext) -> int:
        return get_team_multiplier(context.user.team_id)

    @abstractmethod
    def _get_cache_key(self, context: ThrottleContext) -> str:
        """Return the cache key for rate limiting."""
        ...

    @abstractmethod
    def _get_tokens(self, context: ThrottleContext) -> int | None:
        """Return the number of tokens to consume."""
        ...

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        tokens = self._get_tokens(context)
        if context.model is None or tokens is None:
            return ThrottleResult.allow()

        team_multiplier = self._get_team_multiplier(context)
        limiter = self._get_limiter(context.model, team_multiplier)
        key = self._get_cache_key(context)

        if await limiter.consume(key, tokens):
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=f"{self.token_type} token rate limit exceeded for model {context.model}",
            scope=self.scope,
            retry_after=self.window_seconds,
        )


class InputTokenThrottle(TokenThrottle):
    """Base for input token throttles."""

    limit_key = "input_tph"
    token_type = "Input"

    def _get_tokens(self, context: ThrottleContext) -> int | None:
        return context.input_tokens


class OutputTokenThrottle(TokenThrottle):
    """Base for output token throttles.

    Pre-request: Checks if max_output_tokens would exceed limit (without consuming).
    Post-response: Actual output tokens are consumed via record_output_tokens().
    """

    limit_key = "output_tph"
    token_type = "Output"

    def _get_tokens(self, context: ThrottleContext) -> int | None:
        return context.max_output_tokens

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        """Check if max_output_tokens would be allowed (without consuming)."""
        tokens = self._get_tokens(context)
        if context.model is None or tokens is None:
            return ThrottleResult.allow()

        team_multiplier = self._get_team_multiplier(context)
        limiter = self._get_limiter(context.model, team_multiplier)
        key = self._get_cache_key(context)

        if await limiter.would_allow(key, tokens):
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=f"{self.token_type} token rate limit exceeded for model {context.model}",
            scope=self.scope,
            retry_after=self.window_seconds,
        )

    async def record_output_tokens(self, context: ThrottleContext, actual_tokens: int) -> None:
        """Record actual output tokens after response completes."""
        if context.model is None:
            return

        team_multiplier = self._get_team_multiplier(context)
        limiter = self._get_limiter(context.model, team_multiplier)
        key = self._get_cache_key(context)
        await limiter.consume(key, actual_tokens)


class ProductModelInputTokenThrottle(InputTokenThrottle):
    scope = "product_model_input_tokens"
    limit_multiplier = 10

    def _get_cache_key(self, context: ThrottleContext) -> str:
        team_mult = self._get_team_multiplier(context)
        base = f"product:{context.product}:model:{context.model}:input"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"


class UserModelInputTokenThrottle(InputTokenThrottle):
    scope = "user_model_input_tokens"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        team_mult = self._get_team_multiplier(context)
        base = f"user:{context.user.user_id}:model:{context.model}:input"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"


class ProductModelOutputTokenThrottle(OutputTokenThrottle):
    scope = "product_model_output_tokens"
    limit_multiplier = 10

    def _get_cache_key(self, context: ThrottleContext) -> str:
        team_mult = self._get_team_multiplier(context)
        base = f"product:{context.product}:model:{context.model}:output"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"


class UserModelOutputTokenThrottle(OutputTokenThrottle):
    scope = "user_model_output_tokens"

    def _get_cache_key(self, context: ThrottleContext) -> str:
        team_mult = self._get_team_multiplier(context)
        base = f"user:{context.user.user_id}:model:{context.model}:output"
        if team_mult == 1:
            return base
        return f"{base}:tm{team_mult}"
