from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team

from .base import BaseRecommendation


def _team_has_logs(team_id: int) -> bool:
    result = sync_execute(
        "SELECT 1 FROM logs_distributed WHERE team_id = %(team_id)s LIMIT 1",
        {"team_id": team_id},
    )
    return len(result) > 0


class CrossSellRecommendation(BaseRecommendation):
    """
    Suggests turning on other PostHog products that pair well with error tracking.

    Currently checks:
    - Session replay: pairs nicely because you can see what the user did right
      before the error happened.
    - Logs: correlate application logs with exceptions to speed up debugging.
    """

    type = "cross_sell"

    watched_team_fields = frozenset({"session_recording_opt_in"})

    @classmethod
    def compute(cls, team: Team) -> dict[str, Any]:
        products: list[dict[str, Any]] = [
            {
                "key": "session_replay",
                "name": "Session replay",
                "enable_url": "/settings/environment-replay#replay",
                "enabled": bool(team.session_recording_opt_in),
                "reason": (
                    "Session replay lets you watch exactly what the user was doing right before "
                    "an exception was thrown. Pairing it with error tracking gives you the full "
                    "picture — the stack trace and the user interaction that triggered it."
                ),
            },
            {
                "key": "logs",
                "name": "Logs",
                "enable_url": "/settings/environment-logs#logs",
                "enabled": _team_has_logs(team.id),
                "reason": (
                    "Logs let you correlate application output with exceptions. When an error "
                    "happens, you can jump straight to the logs around the failure instead of "
                    "guessing what the app was doing."
                ),
            },
        ]

        return {"products": products}
