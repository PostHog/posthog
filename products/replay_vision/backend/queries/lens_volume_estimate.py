import datetime as dt
from dataclasses import dataclass

from posthog.schema import RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

# A pathological filter must not be able to hang the estimate request.
_ESTIMATE_MAX_EXECUTION_TIME_SECONDS = 30


@dataclass(frozen=True)
class LensVolumeEstimate:
    matched_sessions: int
    # May be smaller than requested when the team has fewer days of recordings than the window.
    effective_window_days: int


def estimate_lens_session_volume(*, team: Team, query: RecordingsQuery, window_days: int) -> LensVolumeEstimate:
    """Count sessions matching `query` over the last `window_days`, for the lens cost preview.

    Reuses `SessionRecordingListFromQuery`'s filter compilation verbatim and wraps it in a
    COUNT, so the estimate and the real recordings list agree on what "matches".
    """
    windowed = query.model_copy(deep=True)
    windowed.date_from = f"-{window_days}d"
    windowed.date_to = None

    inner = SessionRecordingListFromQuery(team=team, query=windowed).get_query()
    # The inner query groups by session_id, so one row is one session; order is irrelevant to a count.
    inner.order_by = None
    count_query = ast.SelectQuery(
        select=[ast.Call(name="count", args=[])],
        select_from=ast.JoinExpr(table=inner, alias="matched_sessions"),
    )

    response = execute_hogql_query(
        query=count_query,
        team=team,
        query_type="ReplayVisionLensEstimateQuery",
        settings=HogQLGlobalSettings(max_execution_time=_ESTIMATE_MAX_EXECUTION_TIME_SECONDS),
    )
    results = response.results or []
    matched = int(results[0][0]) if results else 0

    return LensVolumeEstimate(
        matched_sessions=matched,
        effective_window_days=_effective_window_days(team=team, requested=window_days),
    )


def _effective_window_days(*, team: Team, requested: int) -> int:
    """Clamp the divisor to the team's actual data span so a new team isn't under-estimated."""
    earliest_query = ast.SelectQuery(
        select=[ast.Call(name="min", args=[ast.Field(chain=["min_first_timestamp"])])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_session_replay_events"])),
    )
    response = execute_hogql_query(
        query=earliest_query,
        team=team,
        query_type="ReplayVisionLensEstimateEarliestQuery",
        settings=HogQLGlobalSettings(max_execution_time=_ESTIMATE_MAX_EXECUTION_TIME_SECONDS),
    )
    results = response.results or []
    earliest = results[0][0] if results else None
    if not isinstance(earliest, dt.datetime):
        return requested

    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=dt.UTC)
    days_of_data = (dt.datetime.now(dt.UTC) - earliest).days + 1
    return max(1, min(requested, days_of_data))
