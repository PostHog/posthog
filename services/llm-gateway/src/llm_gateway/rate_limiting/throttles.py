from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings


def get_team_multiplier(team_id: int | None, scoped_team_ids: Iterable[int] | None = None) -> int:
    """Resolve the rate-limit multiplier for an authenticated user.

    `team_id` is the user's `current_team_id`, which can swap as the user changes
    teams in the UI (so it's not stable across requests with the same key). When the
    bearer token (personal API key or OAuth access token) is scoped to a fixed set
    of teams, we resolve the multiplier across both: the token's scoped teams AND
    the user's current team. The highest multiplier wins — a token scoped to a
    multiplier team (e.g. team 2 at 25x) keeps its boost even if the user is
    currently viewing a different team.
    """
    multipliers = get_settings().team_rate_limit_multipliers
    if not multipliers:
        return 1
    candidates: list[int] = []
    if scoped_team_ids:
        candidates.extend(scoped_team_ids)
    if team_id is not None:
        candidates.append(team_id)
    if not candidates:
        return 1
    return max((multipliers.get(t, 1) for t in candidates), default=1)


@dataclass
class ThrottleContext:
    user: AuthenticatedUser
    product: str
    request_id: str | None = None
    end_user_id: str | None = None
    plan_key: str | None = None
    seat_created_at: str | None = None
    billing_period_start: str | None = None


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
