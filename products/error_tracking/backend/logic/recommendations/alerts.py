from collections import defaultdict
from functools import reduce
from operator import or_
from typing import Any

from django.db.models import Q

from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType

from .base import Recommendation

ALERT_TRIGGERS: list[dict[str, str]] = [
    {"key": "error-tracking-issue-created", "event": "$error_tracking_issue_created"},
    {"key": "error-tracking-issue-reopened", "event": "$error_tracking_issue_reopened"},
    {"key": "error-tracking-issue-spiking", "event": "$error_tracking_issue_spiking"},
]


class AlertsRecommendation(Recommendation):
    type = "alerts"
    refresh_interval = None

    def is_completed(self, meta: dict[str, Any]) -> bool:
        alerts = meta.get("alerts") or []
        return bool(alerts) and all(a.get("enabled") for a in alerts)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        event_filter = reduce(
            or_,
            (Q(filters__contains={"events": [{"id": trigger["event"]}]}) for trigger in ALERT_TRIGGERS),
        )

        rows = (
            HogFunction.objects.filter(
                team_id__in=team_ids,
                type=HogFunctionType.INTERNAL_DESTINATION,
                deleted=False,
            )
            .filter(event_filter)
            .values_list("team_id", "filters")
        )

        events_with_alerts: dict[int, set[str]] = defaultdict(set)
        for team_id, filters in rows:
            for event in (filters or {}).get("events") or []:
                event_id = event.get("id")
                if event_id:
                    events_with_alerts[team_id].add(event_id)

        return {
            team_id: {
                "alerts": [
                    {
                        "key": trigger["key"],
                        "enabled": trigger["event"] in events_with_alerts[team_id],
                    }
                    for trigger in ALERT_TRIGGERS
                ]
            }
            for team_id in team_ids
        }
