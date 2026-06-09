from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team


class Recommendation(ABC):
    type: str
    refresh_interval: timedelta | None = None

    @abstractmethod
    def compute(self, team: Team) -> dict[str, Any]: ...

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Compute metas for many teams at once. Implementations should answer with a
        bounded number of queries regardless of batch size; teams the implementation
        can't answer for may be omitted (the caller reverts them to ready)."""
        return {team.id: self.compute(team) for team in Team.objects.filter(id__in=team_ids)}

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        return meta

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return False
