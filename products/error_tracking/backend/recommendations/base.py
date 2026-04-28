from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team


class Recommendation(ABC):
    type: str
    # None → meta is recomputed on every list request (always live).
    # timedelta → meta is cached and recomputed only when older than the interval.
    # In both cases the recommendation is still persisted so dismissal state survives.
    refresh_interval: timedelta | None = None

    @abstractmethod
    def compute(self, team: Team) -> dict[str, Any]: ...

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        """Hook to overlay live, fast-changing data on top of the cached compute output.
        Runs on every read but is not persisted. Default is identity."""
        return meta
