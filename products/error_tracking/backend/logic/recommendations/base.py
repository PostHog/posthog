from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team


class Recommendation(ABC):
    type: str
    refresh_interval: timedelta | None = None

    @abstractmethod
    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Compute metas for many teams at once, with a bounded number of queries
        regardless of batch size. Must return a meta for every requested team; teams
        omitted from the result are reverted to ready by the caller."""

    def compute(self, team: Team) -> dict[str, Any]:
        return self.compute_batch([team.id])[team.id]

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        return meta

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return False
