from datetime import timedelta
from functools import reduce
from operator import or_
from typing import Any

from django.db.models import Q

from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.team.team import Team

from .base import Recommendation

ALERT_TRIGGERS: list[dict[str, str]] = [
    {"key": "error-tracking-issue-created", "event": "$error_tracking_issue_created"},
    {"key": "error-tracking-issue-reopened", "event": "$error_tracking_issue_reopened"},
    {"key": "error-tracking-issue-spiking", "event": "$error_tracking_issue_spiking"},
]


class AlertsRecommendation(Recommendation):
    type = "alerts"
    refresh_interval = timedelta(seconds=5)

    def compute(self, team: Team) -> dict[str, Any]:
        event_filter = reduce(
            or_,
            (Q(filters__contains={"events": [{"id": trigger["event"]}]}) for trigger in ALERT_TRIGGERS),
        )

        filters_list = (
            HogFunction.objects.filter(
                team_id=team.id,
                type=HogFunctionType.INTERNAL_DESTINATION,
                deleted=False,
            )
            .filter(event_filter)
            .values_list("filters", flat=True)
        )

        events_with_alerts: set[str] = set()
        for filters in filters_list:
            if not filters:
                continue
            for event in filters.get("events") or []:
                event_id = event.get("id")
                if event_id:
                    events_with_alerts.add(event_id)

        return {
            "alerts": [
                {
                    "key": trigger["key"],
                    "enabled": trigger["event"] in events_with_alerts,
                }
                for trigger in ALERT_TRIGGERS
            ]
        }
