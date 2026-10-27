from collections.abc import Callable
from datetime import date
from functools import cached_property
from typing import TypeVar, cast

from django.core.cache import cache

import structlog

from posthog.hogql.errors import ExposedHogQLError

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.scopes import APIScopeObject, scopes_not_covered

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.property_access import restriction_fingerprint
from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    RESOURCE_INHERITANCE_MAP,
    UserAccessControl,
)

from ..facade.contracts import (
    DailyValueNotReady,
    HighlightCandidate,
    HighlightContext,
    HighlightFindings,
    HighlightSource,
)

# Legacy names for the sources still in highlight_sources/. New sources use the facade contract.
Candidate = HighlightCandidate
Found = HighlightFindings

logger = structlog.get_logger(__name__)
T = TypeVar("T")

CACHE_SECONDS = 15 * 60
DAILY_CACHE_SECONDS = 24 * 60 * 60
DAILY_LOCK_SECONDS = 30


def property_restrictions(team: Team, user: User) -> str:
    return restriction_fingerprint(
        get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.id)
    )[:16]


class Context:
    """Today's `HighlightContext`. A source sees only the protocol, so these internals stay private."""

    def __init__(
        self,
        team: Team,
        user: User,
        today: date,
        scopes: frozenset[str] | None = None,
        pinned: frozenset[str] = frozenset(),
    ) -> None:
        self.team = team
        self.user = user
        self.today = today
        self.scopes = scopes
        self.pinned = pinned
        self.failures: list[str] = []
        self.access = UserAccessControl(user=user, team=team)

    @cached_property
    def restrictions(self) -> str:
        # Only daily() reads this. Computing it on first use keeps the context free to build in a source's tests.
        return property_restrictions(self.team, self.user)

    def allows(self, *required: str) -> bool:
        covered = self.scopes is None or "*" in self.scopes or not scopes_not_covered(self.scopes, required)
        return covered and all(self._can_view(scope.split(":")[0]) for scope in required)

    def _can_view(self, resource: str) -> bool:
        governed = RESOURCE_INHERITANCE_MAP.get(cast(APIScopeObject, resource), resource)
        if governed not in ACCESS_CONTROL_RESOURCES:
            return True
        return self.access.check_access_level_for_resource(cast(APIScopeObject, resource), "viewer")

    def daily(self, name: str, compute: Callable[[], T]) -> T:
        key = f"today_highlights:daily:v1:{self.team.id}:{self.restrictions}:{self.today.isoformat()}:{name}"
        cached = cache.get(key)
        if isinstance(cached, tuple):
            return cast(T, cached[0])
        lock = f"{key}:lock"
        if not cache.add(lock, True, DAILY_LOCK_SECONDS):
            raise DailyValueNotReady(name)
        try:
            cached = cache.get(key)
            if isinstance(cached, tuple):
                return cast(T, cached[0])
            value = compute()
            cache.set(key, (value,), DAILY_CACHE_SECONDS)
            return value
        finally:
            cache.delete(lock)

    def guard(self, name: str, provider: Callable[[], T], default: T) -> T:
        try:
            return provider()
        except DailyValueNotReady:
            self.failures.append(name)
            return default
        except Exception as error:
            logger.warning("today_highlights_provider_failed", provider=name, team_id=self.team.id, error=str(error))
            if not isinstance(error, ExposedHogQLError):
                self.failures.append(name)
                capture_exception(error, {"provider": name, "team_id": self.team.id})
            return default


def Source(  # noqa: N802 - keeps the legacy name the sources in highlight_sources/ call
    *, name: str, find: Callable[[Context], HighlightFindings], scopes: tuple[str, ...] = (), pulse_order: int = 0
) -> HighlightSource:
    # A legacy source reads Today's own Context. Today always calls it with one, so the cast holds.
    return HighlightSource(
        name=name,
        find=cast(Callable[[HighlightContext], HighlightFindings], find),
        scopes=scopes,
        pulse_order=pulse_order,
    )
