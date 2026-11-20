"""Per-user limits on report task runs, resolved from the `signal-report-task-limits` flag payload.

A report run (the inbox Implement button, a suggested prompt, `inbox-report-actions-run`, or a tasks create
for a signal report) uses inference the customer does not pay for until a pull request lands, so each user
gets an hourly and a daily budget. The tasks create throttle and the report actions run throttle share one
cache scope per window and both read their limit from `resolve_report_task_run_limits`, so the two paths
always apply the same number.

The payload is keyed by region, because internal flags are shared across US and EU and ids differ:

    {"US": {"default": {"per_hour": 20, "per_day": 50},
            "organizations": {"<organization id>": {"per_day": 150}},
            "teams": {"2": {"per_hour": 60, "per_day": 200}},
            "users": {"<user uuid>": {"per_day": 300}}},
     "EU": {}}

Each field resolves on its own, most specific entry first: user, team (the request's team id, then its
parent project id), organization, `default`, then the code constants. Only the allowed number changes; the
counter stays per user, so a raised project limit applies to the user only in that project.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum

from django.conf import settings

from prometheus_client import Counter
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.signals.backend.scout_harness.team_limits import read_flag_payload

REPORT_TASK_LIMITS_FLAG = "signal-report-task-limits"
# The flag must stay on for everyone, so the payload is served to this id. Overrides live in the payload,
# because one flag has one aggregation type and cannot target users, projects and organizations together.
REPORT_TASK_LIMITS_DISTINCT_ID = "internal_signal_report_task_limits"

DEFAULT_RUNS_PER_HOUR = 20
DEFAULT_RUNS_PER_DAY = 50
# A payload value above these is clamped, so a typo in the flag cannot remove the bound.
MAX_RUNS_PER_HOUR = 100
MAX_RUNS_PER_DAY = 500


class ReportTaskRunWindow(StrEnum):
    HOUR = "hour"
    DAY = "day"


_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("per_hour", DEFAULT_RUNS_PER_HOUR, MAX_RUNS_PER_HOUR),
    ("per_day", DEFAULT_RUNS_PER_DAY, MAX_RUNS_PER_DAY),
)


@frozen
class ReportTaskRunLimits:
    per_hour: int = DEFAULT_RUNS_PER_HOUR
    per_day: int = DEFAULT_RUNS_PER_DAY

    def for_window(self, window: ReportTaskRunWindow) -> int:
        return self.per_hour if window == ReportTaskRunWindow.HOUR else self.per_day


REPORT_TASK_RUNS_THROTTLED = Counter(
    "signals_report_task_runs_throttled",
    "Report task runs refused by the per-user hourly or daily limit.",
    ["window"],
)


def report_task_run_limit_for_request(request: Request, view: APIView, window: ReportTaskRunWindow) -> int:
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


def report_task_run_throttled(window: ReportTaskRunWindow, limit: int, wait: float | None) -> Throttled:
    """The 429 to raise when a limit is reached. It names the limit, so a person knows what to ask to raise."""
    REPORT_TASK_RUNS_THROTTLED.labels(window=window.value).inc()
    period = "an hour" if window == ReportTaskRunWindow.HOUR else "a day"
    return Throttled(
        wait=wait,
        detail=(
            f"You've reached your limit of {limit} report runs {period}. "
            "Try again later, or contact support to raise the limit."
        ),
    )


def resolve_report_task_run_limits(
    *,
    user_uuid: str | None,
    team_id: int | None,
    parent_team_id: int | None,
    organization_id: str | None,
) -> ReportTaskRunLimits:
    """Never raises. Any failure falls back to the code constants, so the flag cannot block or unblock a request."""
    try:
        return limits_from_payload(
            read_flag_payload(REPORT_TASK_LIMITS_FLAG, REPORT_TASK_LIMITS_DISTINCT_ID),
            region=settings.CLOUD_DEPLOYMENT,
            user_uuid=user_uuid,
            team_ids=[team_id, parent_team_id],
            organization_id=organization_id,
        )
    except Exception as error:
        capture_exception(error)
        return ReportTaskRunLimits()


def limits_from_payload(
    payload: object,
    *,
    region: str | None,
    user_uuid: str | None,
    team_ids: Iterable[int | None],
    organization_id: str | None,
) -> ReportTaskRunLimits:
    region_config = payload.get(region.upper()) if isinstance(payload, Mapping) and region else None
    if not isinstance(region_config, Mapping):
        return ReportTaskRunLimits()

    layers = [
        _entry(region_config, "users", [user_uuid]),
        _entry(region_config, "teams", team_ids),
        _entry(region_config, "organizations", [organization_id]),
        region_config.get("default"),
    ]
    resolved: dict[str, int] = {}
    for field, default, ceiling in _FIELDS:
        value = next((v for layer in layers if (v := _positive_int(layer, field)) is not None), default)
        resolved[field] = min(value, ceiling)
    return ReportTaskRunLimits(**resolved)


def _entry(region_config: Mapping, key: str, ids: Iterable[object]) -> object:
    entries = region_config.get(key)
    if not isinstance(entries, Mapping):
        return None
    for entry_id in ids:
        if entry_id is not None and isinstance(entry := entries.get(str(entry_id)), Mapping):
            return entry
    return None


def _positive_int(layer: object, field: str) -> int | None:
    if not isinstance(layer, Mapping):
        return None
    value = layer.get(field)
    # bool is an int subclass, and `true` in the payload must not read as a limit of 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value
