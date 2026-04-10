from typing import Any

from posthog.models.team.team import Team

from .base import BaseRecommendation


class CrossSellRecommendation(BaseRecommendation):
    """
    Suggests turning on other PostHog products that pair well with error tracking.

    Currently checks:
    - Session replay: pairs nicely because you can see what the user did right
      before the error happened.
    - Logs: correlate application logs with exceptions to speed up debugging.
    """

    type = "cross_sell"

    watched_team_fields = frozenset({"session_recording_opt_in", "logs_settings"})

    @classmethod
    def compute(cls, team: Team) -> dict[str, Any]:
        products: list[dict[str, Any]] = []

        if not team.session_recording_opt_in:
            products.append(
                {
                    "key": "session_replay",
                    "name": "Session replay",
                    "enable_url": "/settings/environment-replay#replay",
                    "reason": (
                        "Session replay lets you watch exactly what the user was doing right before "
                        "an exception was thrown. Pairing it with error tracking gives you the full "
                        "picture — the stack trace and the user interaction that triggered it."
                    ),
                }
            )

        logs_settings = team.logs_settings or {}
        if not logs_settings.get("capture_console_logs"):
            products.append(
                {
                    "key": "logs",
                    "name": "Logs",
                    "enable_url": "/settings/environment-logs#logs",
                    "reason": (
                        "Logs let you correlate application output with exceptions. When an error "
                        "happens, you can jump straight to the logs around the failure instead of "
                        "guessing what the app was doing."
                    ),
                }
            )

        return {"products": products}
