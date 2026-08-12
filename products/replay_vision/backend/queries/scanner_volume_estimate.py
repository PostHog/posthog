import datetime as dt
from dataclasses import dataclass

from django.utils import timezone

from posthog.schema import FilterLogicalOperator, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, SamplingMode
from products.replay_vision.backend.queries.scanner_candidate_query import (
    eligibility_predicates,
    surfacing_score_predicate,
)

# A pathological filter must not be able to hang the estimate request.
_ESTIMATE_MAX_EXECUTION_TIME_SECONDS = 30

# Interactive saves get a tighter budget and fail soft; the batch refresher can afford the full cap.
ESTIMATE_INTERACTIVE_MAX_EXECUTION_SECONDS = 10

# The estimate always projects to a calendar month.
ESTIMATE_WINDOW_DAYS = 30
# Scan a week and extrapolate: a 30-day scan of event-filtered queries reads billions of rows and blows the budget.
_ESTIMATE_SCAN_WINDOW_DAYS = 7
# The editor's cost preview re-estimates on every filter tweak, so it gets an order-of-magnitude answer from a
# single day; the durable per-scanner number still comes from the batch refresher's full window.
ESTIMATE_INTERACTIVE_SCAN_WINDOW_DAYS = 1
# Events subqueries additionally SAMPLE users at 10%; matched counts are corrected back up.
_ESTIMATE_EVENTS_SAMPLE_FACTOR = 0.1
# When sampling is off (OR-operand filters), a full-width scan is the only option, so bound its window instead.
_ESTIMATE_UNSAMPLED_SCAN_WINDOW_DAYS = 2

# Persisted per-scanner estimates older than this are recomputed by the sweep.
ESTIMATE_STALE_AFTER = dt.timedelta(hours=24)


@dataclass(frozen=True)
class ScannerVolumeEstimate:
    matched_sessions: int
    # May be smaller than the scan window when the team has fewer days of recordings.
    effective_window_days: int


def estimate_scanner_session_volume(
    *,
    team: Team,
    query: RecordingsQuery,
    sampling_mode: SamplingMode | str = SamplingMode.COMPREHENSIVE,
    max_execution_seconds: int = _ESTIMATE_MAX_EXECUTION_TIME_SECONDS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
    scan_window_days: int = _ESTIMATE_SCAN_WINDOW_DAYS,
) -> ScannerVolumeEstimate:
    """Count sessions matching `query` over a recent window, for the scanner cost preview.

    Reuses `SessionRecordingListFromQuery`'s filter compilation (with events subqueries sampled
    at 10% and corrected back up) wrapped in a COUNT, so the estimate and the real recordings
    list agree on what "matches"; `project_monthly_observations` extrapolates to 30 days. The team's
    earliest recent recording is fetched in the same round trip via a CROSS JOIN so the
    cost-preview widget never pays for two sequential HogQL queries.
    """
    # Sampling is only sound when every match must pass the sampled events leg; under OR, sessions
    # matched via unsampled branches (persons, cohorts, console logs) would be multiplied by the correction.
    sample_factor = None if query.operand == FilterLogicalOperator.OR_ else _ESTIMATE_EVENTS_SAMPLE_FACTOR
    if sample_factor is None:
        scan_window_days = min(scan_window_days, _ESTIMATE_UNSAMPLED_SCAN_WINDOW_DAYS)

    now = dt.datetime.now(dt.UTC)
    window_start = now - dt.timedelta(days=scan_window_days)
    windowed = query.model_copy(deep=True)
    # Exact timestamp — the relative date form truncates to start-of-day, over-counting a day against the divisor.
    windowed.date_from = window_start.isoformat()
    windowed.date_to = None

    # Count only sessions the sweep would actually observe, so the forecast matches the eligible set the candidate query selects.
    extra_having = eligibility_predicates()
    if (surfacing := surfacing_score_predicate(sampling_mode)) is not None:
        extra_having.append(surfacing)
    list_query = SessionRecordingListFromQuery(
        team=team,
        query=windowed,
        extra_having_predicates=extra_having,
        events_sample_factor=sample_factor,
    )
    inner = list_query.get_query()
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
        # Bounded so the probe partition-prunes; older data clamps the divisor to the scan window anyway.
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["min_first_timestamp"]),
            right=ast.Constant(value=now - dt.timedelta(days=scan_window_days + 1)),
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
        ch_user=ch_user,
    )
    results = response.results or []
    matched = int(results[0][0]) if results else 0
    if list_query.events_subqueries_sampled:
        matched = round(matched / _ESTIMATE_EVENTS_SAMPLE_FACTOR)
    earliest = results[0][1] if results else None

    return ScannerVolumeEstimate(
        matched_sessions=matched,
        effective_window_days=_clamp_window_days(earliest, scan_window_days),
    )


def project_monthly_observations(estimate: ScannerVolumeEstimate, sampling_rate: float) -> int:
    """Scale matched sessions to a 30-day month and apply the sampling rate."""
    return round(estimate.matched_sessions / estimate.effective_window_days * ESTIMATE_WINDOW_DAYS * sampling_rate)


def refresh_scanner_estimate(
    scanner: ReplayScanner,
    *,
    max_execution_seconds: int = _ESTIMATE_MAX_EXECUTION_TIME_SECONDS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> None:
    """Recompute and persist the scanner's projected monthly volume. Raises on failure; callers decide severity."""
    estimate = estimate_scanner_session_volume(
        team=scanner.team,
        query=scanner.recordings_query(),
        sampling_mode=scanner.sampling_mode,
        max_execution_seconds=max_execution_seconds,
        ch_user=ch_user,
    )
    projection = project_monthly_observations(estimate, scanner.sampling_rate)
    estimated_at = timezone.now()
    # Filtered write so a config edit racing the (slow) estimate query can't get stamped fresh with stale numbers.
    updated = ReplayScanner.objects.filter(
        pk=scanner.pk, query=scanner.query, sampling_rate=scanner.sampling_rate, sampling_mode=scanner.sampling_mode
    ).update(estimated_monthly_observations=projection, estimated_at=estimated_at)
    if updated:
        scanner.estimated_monthly_observations = projection
        scanner.estimated_at = estimated_at


def _clamp_window_days(earliest: object, scan_window_days: int) -> int:
    """Clamp the divisor to the team's actual data span so a new team isn't under-estimated."""
    if not isinstance(earliest, dt.datetime):
        # The probe covers the whole scan window, so no-earliest implies matched == 0 and any divisor projects 0.
        return scan_window_days
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=dt.UTC)
    days_of_data = (dt.datetime.now(dt.UTC) - earliest).days + 1
    return max(1, min(scan_window_days, days_of_data))
