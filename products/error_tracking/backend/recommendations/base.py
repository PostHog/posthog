from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team


class Recommendation(ABC):
    type: str
    refresh_interval: timedelta

    @abstractmethod
    def compute(self, team: Team) -> dict[str, Any]: ...
