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
