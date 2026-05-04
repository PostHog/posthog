from datetime import timedelta
from typing import Any

from posthog.models.team.team import Team

from products.logs.backend.has_logs_query_runner import team_has_logs

from .base import Recommendation


class CrossSellRecommendation(Recommendation):
    type = "cross_sell"
    refresh_interval = timedelta(seconds=30)

    def compute(self, team: Team) -> dict[str, Any]:
        return {
            "products": [
                {
                    "key": "session_replay",
                    "enabled": bool(team.session_recording_opt_in),
                },
                {
                    "key": "logs",
                    "enabled": team_has_logs(team),
                },
            ]
        }
