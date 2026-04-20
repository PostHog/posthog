from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User


class Recommendation(ABC):
    type: str
    refresh_interval: timedelta
    # If True, recommendations are computed/stored per-user-per-team (so dismissal
    # and freshness are tracked independently for each user). If False (default),
    # a single row per team is shared across all members.
    user_scoped: bool = False

    @abstractmethod
    def compute(self, team: Team, user: User | None = None) -> dict[str, Any]: ...

    def completion_progress(self, meta: dict[str, Any]) -> float:
        """Fraction of the recommendation's action(s) the user has completed, in [0, 1].

        Default for single-action recs: `meta["enabled"]` → 1.0, else 0.0.
        Multi-item recs override this (e.g. fraction of enabled items).
        """
        return 1.0 if meta.get("enabled") else 0.0
