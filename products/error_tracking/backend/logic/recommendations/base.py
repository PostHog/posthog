from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team


class Recommendation(ABC):
    type: str
    refresh_interval: timedelta | None = None
    # Recommendations with the same refresh group go stale at the same moment, so the sweep computes them in the
    # same run and they can share query results. Defaults to the type.
    refresh_group: str | None = None
    # The most teams one compute_batch call gets from the sweep. None means the whole batch.
    max_teams_per_compute: int | None = None

    @abstractmethod
    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Compute metas for many teams at once, with a bounded number of queries
        regardless of batch size. A data source that only reads one team at a time, such as
        a HogQL system table, may be read per team. Must return a meta for every requested
        team; teams omitted from the result are reverted to ready by the caller."""

    def compute(self, team: Team) -> dict[str, Any]:
        return self.compute_batch([team.id])[team.id]

    def is_enabled_for_team(self, team: Team) -> bool:
        """Teams this returns False for get no new row and no compute. Rows from before are hidden on read."""
        return True

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        return meta

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return False
