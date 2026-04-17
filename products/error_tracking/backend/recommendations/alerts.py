from datetime import timedelta
from typing import Any

from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.team.team import Team

from .base import Recommendation

ALERT_TRIGGERS: list[dict[str, str]] = [
    {"key": "error-tracking-issue-created", "event": "$error_tracking_issue_created"},
    {"key": "error-tracking-issue-reopened", "event": "$error_tracking_issue_reopened"},
    {"key": "error-tracking-issue-spiking", "event": "$error_tracking_issue_spiking"},
]


def _team_has_alert_for_event(team_id: int, event_id: str) -> bool:
    return HogFunction.objects.filter(
        team_id=team_id,
        type=HogFunctionType.INTERNAL_DESTINATION,
        deleted=False,
        filters__contains={"events": [{"id": event_id}]},
    ).exists()


class AlertsRecommendation(Recommendation):
    type = "alerts"
    refresh_interval = timedelta(seconds=5)

    def compute(self, team: Team) -> dict[str, Any]:
        return {
            "alerts": [
                {
                    "key": trigger["key"],
                    "enabled": _team_has_alert_for_event(team.id, trigger["event"]),
                }
                for trigger in ALERT_TRIGGERS
            ]
        }
