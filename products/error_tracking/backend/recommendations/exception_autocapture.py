from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User

from .base import Recommendation


class ExceptionAutocaptureRecommendation(Recommendation):
    type = "exception_autocapture"
    refresh_interval = timedelta(seconds=5)

    def compute(self, team: Team, user: User | None = None) -> dict[str, Any]:
        return {"enabled": bool(team.autocapture_exceptions_opt_in)}
