from typing import Any

from rest_framework.request import Request
from rest_framework.throttling import UserRateThrottle

from posthog.oauth_provenance import get_oauth_access_token
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle


class ReportMetricRefreshThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "report_metric_refresh"
    rate = "10/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"team_{team_id}"}
        return super().get_cache_key(request, view)


class _ReportTaskActionRunThrottle(UserRateThrottle):
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        # A scout acts as a person, so its runs get their own bucket per task. The scout's daily cap bounds them.
        if (sandbox_task_id := getattr(get_oauth_access_token(request), "sandbox_task_id", None)) is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"sandbox_task_{sandbox_task_id}"}
        return super().get_cache_key(request, view)


class ReportTaskActionRunBurstThrottle(_ReportTaskActionRunThrottle):
    # Scope and rate match the tasks create throttle for report tasks, so a run started from the
    # API spends the same per-user budget as one started from the inbox.
    scope = "signal_report_task_create_burst"
    rate = "20/hour"


class ReportTaskActionRunSustainedThrottle(_ReportTaskActionRunThrottle):
    scope = "signal_report_task_create_day"
    rate = "50/day"


class UserReportCreateBurstThrottle(UserRateThrottle):
    # The daily cap counts stored reports, and a report is stored only after the safety judge returns.
    # This rate limits how far parallel creates can pass the cap during that wait.
    scope = "signal_report_user_create_burst"
    rate = "10/minute"


class _SourceFilterPreviewThrottle(PersonalApiKeyOrUserRateThrottle):
    # Each preview runs two ClickHouse queries over the source's warehouse table, so the budget is per project and
    # covers every auth method. The ClickHouse throttles in posthog.rate_limit skip session and OAuth requests.
    def get_cache_key(self, request: Request, view: Any) -> str | None:
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"team_{team_id}"}
        return super().get_cache_key(request, view)


class SourceFilterPreviewBurstThrottle(_SourceFilterPreviewThrottle):
    scope = "signal_source_filter_preview_burst"
    rate = "30/minute"


class SourceFilterPreviewSustainedThrottle(_SourceFilterPreviewThrottle):
    scope = "signal_source_filter_preview_sustained"
    rate = "300/hour"


class ReportSearchThrottle(PersonalApiKeyOrUserRateThrottle):
    # Per project, because a semantic search reads every report vector of the project from ClickHouse
    # and a fleet of scouts shares one project's budget.
    scope = "signal_report_search"
    rate = "120/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"team_{team_id}"}
        return super().get_cache_key(request, view)
