from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team


class Recommendation(ABC):
    type: str
    refresh_interval: timedelta | None = None

    @abstractmethod
    def compute(self, team: Team) -> dict[str, Any]: ...

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        return meta

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return False

    def emit_signals(self, team: Team, old_meta: dict[str, Any], new_meta: dict[str, Any]) -> None:
        """Emit signals for entries that are new relative to the previously computed meta."""
        return
