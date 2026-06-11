from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings


def get_rate_limit_multiplier(user: AuthenticatedUser) -> int:
    settings = get_settings()
    staff_multiplier = settings.staff_rate_limit_multiplier if user.is_staff else 1
    team_multiplier = settings.team_rate_limit_multipliers.get(user.team_id, 1) if user.team_id is not None else 1
    return max(staff_multiplier, team_multiplier)


@dataclass
class ThrottleContext:
    user: AuthenticatedUser
    product: str
    request_id: str | None = None
    end_user_id: str | None = None
    plan_key: str | None = None
    seat_created_at: str | None = None
    billing_period_start: str | None = None
    ai_credits_exhausted: bool = False


@dataclass
class ThrottleResult:
    allowed: bool
    status_code: int = 429
    detail: str = "Rate limit exceeded"
    scope: str | None = None
    retry_after: int | None = None
    used_usd: float | None = None
    limit_usd: float | None = None

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
        used_usd: float | None = None,
        limit_usd: float | None = None,
    ) -> ThrottleResult:
        return cls(
            allowed=False,
            status_code=status_code,
            detail=detail,
            scope=scope,
            retry_after=retry_after,
            used_usd=used_usd,
            limit_usd=limit_usd,
        )


class Throttle(ABC):
    scope: str = "default"

    @abstractmethod
    async def allow_request(self, context: ThrottleContext) -> ThrottleResult: ...
