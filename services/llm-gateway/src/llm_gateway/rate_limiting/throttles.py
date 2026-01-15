from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from llm_gateway.auth.models import AuthenticatedUser


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
