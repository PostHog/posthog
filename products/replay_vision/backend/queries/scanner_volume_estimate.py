import datetime as dt
from dataclasses import dataclass

from django.utils import timezone

from posthog.schema import RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries.scanner_candidate_query import eligibility_predicates

# A pathological filter must not be able to hang the estimate request.
_ESTIMATE_MAX_EXECUTION_TIME_SECONDS = 30

# Interactive saves get a tighter budget and fail soft; the batch refresher can afford the full cap.
ESTIMATE_INTERACTIVE_MAX_EXECUTION_SECONDS = 10

# The estimate always projects a calendar month from a fixed 30-day lookback.
ESTIMATE_WINDOW_DAYS = 30

# The earliest-recording probe scans at most this far back; anything older clamps the divisor to the full window.
_EARLIEST_PROBE_LOOKBACK_DAYS = 3 * ESTIMATE_WINDOW_DAYS

# Persisted per-scanner estimates older than this are recomputed by the sweep.
ESTIMATE_STALE_AFTER = dt.timedelta(hours=24)


@dataclass(frozen=True)
class ScannerVolumeEstimate:
    matched_sessions: int
    # May be smaller than ESTIMATE_WINDOW_DAYS when the team has fewer days of recordings.
    effective_window_days: int


def estimate_scanner_session_volume(
    *, team: Team, query: RecordingsQuery, max_execution_seconds: int = _ESTIMATE_MAX_EXECUTION_TIME_SECONDS
) -> ScannerVolumeEstimate:
    """Count sessions matching `query` over the last 30 days, for the scanner cost preview.

    Reuses `SessionRecordingListFromQuery`'s filter compilation verbatim and wraps it in a
    COUNT, so the estimate and the real recordings list agree on what "matches". The team's
    earliest recent recording is fetched in the same round trip via a CROSS JOIN so the
    cost-preview widget never pays for two sequential HogQL queries.
    """
    now = dt.datetime.now(dt.UTC)
    window_start = now - dt.timedelta(days=ESTIMATE_WINDOW_DAYS)
    windowed = query.model_copy(deep=True)
    # Exact timestamp — the relative "-30d" form truncates to start-of-day, counting up to 31 days against a /30 divisor.
    windowed.date_from = window_start.isoformat()
    windowed.date_to = None

    # Count only sessions the sweep would actually observe, so the forecast matches the eligible set the candidate query selects.
    inner = SessionRecordingListFromQuery(
        team=team, query=windowed, extra_having_predicates=eligibility_predicates()
    ).get_query()
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
        # Bounded so the probe partition-prunes; older data would clamp the divisor to the full window anyway.
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["min_first_timestamp"]),
            right=ast.Constant(value=now - dt.timedelta(days=_EARLIEST_PROBE_LOOKBACK_DAYS)),
        ),
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

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=combined_query,
        team=team,
        query_type="ReplayVisionScannerEstimateQuery",
        settings=HogQLGlobalSettings(max_execution_time=max_execution_seconds),
    )
    results = response.results or []
    matched = int(results[0][0]) if results else 0
    earliest = results[0][1] if results else None

    return ScannerVolumeEstimate(
        matched_sessions=matched,
        effective_window_days=_clamp_window_days(earliest),
    )


def project_monthly_observations(estimate: ScannerVolumeEstimate, sampling_rate: float) -> int:
    """Scale matched sessions to a 30-day month and apply the sampling rate."""
    return round(estimate.matched_sessions / estimate.effective_window_days * ESTIMATE_WINDOW_DAYS * sampling_rate)


def refresh_scanner_estimate(
    scanner: ReplayScanner, *, max_execution_seconds: int = _ESTIMATE_MAX_EXECUTION_TIME_SECONDS
) -> None:
    """Recompute and persist the scanner's projected monthly volume. Raises on failure; callers decide severity."""
    estimate = estimate_scanner_session_volume(
        team=scanner.team, query=scanner.recordings_query(), max_execution_seconds=max_execution_seconds
    )
    projection = project_monthly_observations(estimate, scanner.sampling_rate)
    estimated_at = timezone.now()
    # Filtered write so a config edit racing the (slow) estimate query can't get stamped fresh with stale numbers.
    updated = ReplayScanner.objects.filter(
        pk=scanner.pk, query=scanner.query, sampling_rate=scanner.sampling_rate
    ).update(estimated_monthly_observations=projection, estimated_at=estimated_at)
    if updated:
        scanner.estimated_monthly_observations = projection
        scanner.estimated_at = estimated_at


def _clamp_window_days(earliest: object) -> int:
    """Clamp the divisor to the team's actual data span so a new team isn't under-estimated."""
    if not isinstance(earliest, dt.datetime):
        return ESTIMATE_WINDOW_DAYS
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=dt.UTC)
    days_of_data = (dt.datetime.now(dt.UTC) - earliest).days + 1
    return max(1, min(ESTIMATE_WINDOW_DAYS, days_of_data))
