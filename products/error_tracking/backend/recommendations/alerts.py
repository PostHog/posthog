from datetime import timedelta
from typing import Any

from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.team.team import Team

from .base import Recommendation

ALERT_EVENT_BY_KEY: dict[str, str] = {
    "issue_created": "$error_tracking_issue_created",
    "issue_reopened": "$error_tracking_issue_reopened",
    "issue_spiking": "$error_tracking_issue_spiking",
}


def _team_has_alert_for_event(team_id: int, event: str) -> bool:
    return HogFunction.objects.filter(
        team_id=team_id,
        deleted=False,
        type=HogFunctionType.INTERNAL_DESTINATION,
        filters__contains={"events": [{"id": event, "type": "events"}]},
    ).exists()


class AlertsRecommendation(Recommendation):
    type = "alerts"
    refresh_interval = timedelta(seconds=5)

    def compute(self, team: Team) -> dict[str, Any]:
        return {
            "alerts": [
                {"key": key, "enabled": _team_has_alert_for_event(team.id, event)}
                for key, event in ALERT_EVENT_BY_KEY.items()
            ]
        }
