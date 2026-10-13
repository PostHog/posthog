from typing import Any

from rest_framework.request import Request

from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle


class ReportMetricRefreshThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "report_metric_refresh"
    rate = "10/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"team_{team_id}"}
        return super().get_cache_key(request, view)
