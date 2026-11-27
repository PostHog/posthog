from typing import Any

from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.oauth_provenance import get_oauth_access_token
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

from products.signals.backend.report_task_limits import (
    DEFAULT_RUNS_PER_DAY,
    DEFAULT_RUNS_PER_HOUR,
    ReportTaskRunLimits,
    ReportTaskRunWindow,
    report_task_run_refused,
    resolve_report_task_run_limits,
)

_REFUSING_THROTTLE_ATTR = "report_task_run_refusing_throttle"


class ReportMetricRefreshThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "report_metric_refresh"
    rate = "10/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        team_id = self.safely_get_team_id_from_view(view)
        if team_id is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"team_{team_id}"}
        return super().get_cache_key(request, view)


class _ReportTaskActionRunThrottle(UserRateThrottle):
    window: ReportTaskRunWindow

    def allow_request(self, request: Request, view: APIView) -> bool:
        # A scout's bucket keeps the default limit, so raising a person's limit does not raise their scouts'.
        if _sandbox_task_id(request) is None:
            self.num_requests = _limit_for_request(request, view, self.window)
        if super().allow_request(request, view):
            return True
        # DRF checks every window before it refuses, so the view can name the one with the longest wait.
        refusing = getattr(request, _REFUSING_THROTTLE_ATTR, None)
        if refusing is None or (self.wait() or 0) > (refusing.wait() or 0):
            setattr(request, _REFUSING_THROTTLE_ATTR, self)
        return False

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        # A scout acts as a person, so its runs get their own bucket per task. The scout's daily cap bounds them.
        if (sandbox_task_id := _sandbox_task_id(request)) is not None:
            return self.cache_format % {"scope": self.scope, "ident": f"sandbox_task_{sandbox_task_id}"}
        return super().get_cache_key(request, view)


def _sandbox_task_id(request: Request) -> object:
    return getattr(get_oauth_access_token(request), "sandbox_task_id", None)


def _limit_for_request(request: Request, view: APIView, window: ReportTaskRunWindow) -> int:
    """The limit that applies to the requesting user in the project the request is made in."""
    try:
        team = getattr(view, "team", None)
        user_uuid = getattr(request.user, "uuid", None)
        limits = resolve_report_task_run_limits(
            user_uuid=str(user_uuid) if user_uuid else None,
            team_id=getattr(team, "id", None),
            parent_team_id=getattr(team, "parent_team_id", None),
            organization_id=str(team.organization_id) if team is not None else None,
        )
    except Exception as error:
        capture_exception(error)
        limits = ReportTaskRunLimits()
    return limits.for_window(window)


def report_task_run_throttled(request: Request, wait: float | None) -> Throttled | None:
    """The 429 for a request a report run limit refused, or None when another throttle refused it."""
    refusing = getattr(request, _REFUSING_THROTTLE_ATTR, None)
    if refusing is None:
        return None
    return Throttled(wait=wait, detail=report_task_run_refused(refusing.window, refusing.num_requests))


class ReportTaskActionRunBurstThrottle(_ReportTaskActionRunThrottle):
    # Scope and rate match the tasks create throttle for report tasks, so a run started from the
    # API spends the same per-user budget as one started from the inbox. The rate sets only the window;
    # the number comes from the `signal-report-task-limits` flag payload on each request.
    scope = "signal_report_task_create_burst"
    rate = f"{DEFAULT_RUNS_PER_HOUR}/hour"
    window = ReportTaskRunWindow.HOUR


class ReportTaskActionRunSustainedThrottle(_ReportTaskActionRunThrottle):
    scope = "signal_report_task_create_day"
    rate = f"{DEFAULT_RUNS_PER_DAY}/day"
    window = ReportTaskRunWindow.DAY


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


class SourceFilterValidateBurstThrottle(_SourceFilterPreviewThrottle):
    # The editor checks the expression on each typing pause, and the check reads no warehouse data.
    scope = "signal_source_filter_validate_burst"
    rate = "120/minute"


class SourceFilterValidateSustainedThrottle(_SourceFilterPreviewThrottle):
    scope = "signal_source_filter_validate_sustained"
    rate = "3000/hour"


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
