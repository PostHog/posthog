from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.token_bucket import TokenBucketLimiter


@dataclass
class ThrottleContext:
    user: AuthenticatedUser
    product: str
    model: str | None = None
    input_tokens: int | None = None
    max_output_tokens: int | None = None
    request_id: str | None = None


@dataclass
class ThrottleResult:
    allowed: bool
    status_code: int = 429
    detail: str = "Rate limit exceeded"
    scope: str | None = None

    @classmethod
    def allow(cls) -> ThrottleResult:
        return cls(allowed=True)

    @classmethod
    def deny(
        cls,
        status_code: int = 429,
        detail: str = "Rate limit exceeded",
        scope: str | None = None,
    ) -> ThrottleResult:
        return cls(allowed=False, status_code=status_code, detail=detail, scope=scope)


class Throttle(ABC):
    scope: str = "default"

    @abstractmethod
    async def allow_request(self, context: ThrottleContext) -> ThrottleResult: ...


class RateThrottle(Throttle):
    scope: str = "rate"
    rate: str = "100/minute"

    def __init__(self, rate: str | None = None):
        if rate is not None:
            self.rate = rate
        self._limiter = self._create_limiter()

    def _create_limiter(self) -> TokenBucketLimiter:
        num_requests, duration = self._parse_rate(self.rate)
        return TokenBucketLimiter(
            rate=num_requests / duration,
            capacity=float(num_requests),
        )

    @staticmethod
    def _parse_rate(rate: str) -> tuple[int, int]:
        num, period = rate.split("/")
        durations = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        return int(num), durations[period]

    @abstractmethod
    def get_cache_key(self, context: ThrottleContext) -> str: ...

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        key = self.get_cache_key(context)
        if self._limiter.consume(key):
            return ThrottleResult.allow()
        return ThrottleResult.deny(scope=self.scope)
