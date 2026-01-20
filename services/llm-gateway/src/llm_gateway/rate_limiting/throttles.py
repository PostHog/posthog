from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings


def get_team_multiplier(team_id: int | None) -> int:
    if team_id is None:
        return 1

    return get_settings().team_rate_limit_multipliers.get(team_id, 1)


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
    retry_after: int | None = None

    @classmethod
    def allow(cls) -> ThrottleResult:
        return cls(allowed=True)

    @classmethod
    def deny(
        cls,
        status_code: int = 429,
        detail: str = "Rate limit exceeded",
        scope: str | None = None,
        retry_after: int | None = None,
    ) -> ThrottleResult:
        return cls(allowed=False, status_code=status_code, detail=detail, scope=scope, retry_after=retry_after)


class Throttle(ABC):
    scope: str = "default"

    @abstractmethod
    async def allow_request(self, context: ThrottleContext) -> ThrottleResult: ...
