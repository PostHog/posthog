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

# The estimate always projects a calendar month from a fixed 30-day lookback.
ESTIMATE_WINDOW_DAYS = 30


@dataclass(frozen=True)
class ScannerVolumeEstimate:
    matched_sessions: int
    # May be smaller than ESTIMATE_WINDOW_DAYS when the team has fewer days of recordings.
    effective_window_days: int


def estimate_scanner_session_volume(*, team: Team, query: RecordingsQuery) -> ScannerVolumeEstimate:
    """Count sessions matching `query` over the last 30 days, for the scanner cost preview.

    Reuses `SessionRecordingListFromQuery`'s filter compilation verbatim and wraps it in a
    COUNT, so the estimate and the real recordings list agree on what "matches". The team's
    earliest recording is fetched in the same round trip via a CROSS JOIN so the cost-preview
    widget never pays for two sequential HogQL queries.
    """
    windowed = query.model_copy(deep=True)
    windowed.date_from = f"-{ESTIMATE_WINDOW_DAYS}d"
    windowed.date_to = None

    inner = SessionRecordingListFromQuery(team=team, query=windowed).get_query()
    # The inner query groups by session_id, so one row is one session; order is irrelevant to a count.
    inner.order_by = None

    matched_subquery = ast.SelectQuery(
        select=[ast.Alias(alias="matched", expr=ast.Call(name="count", args=[]))],
        select_from=ast.JoinExpr(table=inner, alias="_matched"),
    )
    earliest_subquery = ast.SelectQuery(
        select=[
            ast.Alias(
                alias="earliest",
                expr=ast.Call(name="min", args=[ast.Field(chain=["min_first_timestamp"])]),
            )
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_session_replay_events"])),
    )
    combined_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["m", "matched"]),
            ast.Field(chain=["e", "earliest"]),
        ],
        select_from=ast.JoinExpr(
            table=matched_subquery,
            alias="m",
            next_join=ast.JoinExpr(
                join_type="CROSS JOIN",
                table=earliest_subquery,
                alias="e",
            ),
        ),
    )

    response = execute_hogql_query(
        query=combined_query,
        team=team,
        query_type="ReplayVisionScannerEstimateQuery",
        settings=HogQLGlobalSettings(max_execution_time=_ESTIMATE_MAX_EXECUTION_TIME_SECONDS),
    )
    results = response.results or []
    matched = int(results[0][0]) if results else 0
    earliest = results[0][1] if results else None

    return ScannerVolumeEstimate(
        matched_sessions=matched,
        effective_window_days=_clamp_window_days(earliest),
    )


def _clamp_window_days(earliest: object) -> int:
    """Clamp the divisor to the team's actual data span so a new team isn't under-estimated."""
    if not isinstance(earliest, dt.datetime):
        return ESTIMATE_WINDOW_DAYS
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=dt.UTC)
    days_of_data = (dt.datetime.now(dt.UTC) - earliest).days + 1
    return max(1, min(ESTIMATE_WINDOW_DAYS, days_of_data))
