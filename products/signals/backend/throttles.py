from typing import Any

from rest_framework.request import Request
from rest_framework.throttling import UserRateThrottle

from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle


class ReportMetricRefreshThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "report_metric_refresh"
    rate = "10/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"team_{team_id}"}
        return super().get_cache_key(request, view)


class ReportTaskActionRunBurstThrottle(UserRateThrottle):
    # Scope and rate match the tasks create throttle for report tasks, so a run started from the
    # API spends the same per-user budget as one started from the inbox.
    scope = "signal_report_task_create_burst"
    rate = "20/hour"


class ReportTaskActionRunSustainedThrottle(UserRateThrottle):
    scope = "signal_report_task_create_day"
    rate = "50/day"
