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

# The estimate always projects to a calendar month.
ESTIMATE_WINDOW_DAYS = 30
# Events subqueries additionally SAMPLE users at 10%; matched counts are corrected back up.
_ESTIMATE_EVENTS_SAMPLE_FACTOR = 0.1


@dataclass(frozen=True, kw_only=True)
class EstimateBudget:
    """What a single estimate may spend. Keyword-only because the fields are plain counts, so
    positional arguments would let a call site swap them without any type error.

    Only windows that are whole weeks are safe to persist. A shorter one inherits whichever weekdays
    it happened to land on, which biases the monthly projection instead of merely adding noise.
    """

    # A pathological filter must not be able to hang the caller.
    max_execution_seconds: int
    # Scanning a slice and extrapolating: a 30-day scan of event-filtered queries reads billions of rows.
    scan_window_days: int
    # Used when the operand rules out sampling, which makes the scan full price. None keeps one window
    # for both cases, which is what any estimate that gets persisted needs.
    unsampled_scan_window_days: int | None = None

    def window_days(self, *, unsampled: bool) -> int:
        if unsampled and self.unsampled_scan_window_days is not None:
            return self.unsampled_scan_window_days
        return self.scan_window_days


# The refresher recomputes at most daily per scanner, so it can afford the full window.
BATCH_ESTIMATE_BUDGET = EstimateBudget(max_execution_seconds=30, scan_window_days=7)
# A save blocks the request, so it gets a tighter clock and fails soft. It still writes the persisted
# number, so the window stays a whole week.
SAVE_ESTIMATE_BUDGET = EstimateBudget(max_execution_seconds=10, scan_window_days=7)
# The editor's cost preview and Max both re-estimate freely and neither result is persisted, so where
# sampling is unavailable they take an order-of-magnitude answer from a shorter window.
PREVIEW_ESTIMATE_BUDGET = EstimateBudget(max_execution_seconds=10, scan_window_days=7, unsampled_scan_window_days=2)

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
    ch_user: ClickHouseUser = ClickHouseUser.APP,
    budget: EstimateBudget = BATCH_ESTIMATE_BUDGET,
) -> ScannerVolumeEstimate:
    """Count sessions matching `query` over a recent window, for the scanner cost preview.

    Reuses `SessionRecordingListFromQuery`'s filter compilation (with events subqueries sampled
    at 10% and corrected back up) wrapped in a COUNT, so the estimate and the real recordings
    list agree on what "matches"; `project_monthly_observations` extrapolates to 30 days. The team's
    earliest recent recording is fetched in the same round trip via a CROSS JOIN so the
    cost-preview widget never pays for two sequential HogQL queries.
    """
    # Sampling is only sound when every match must pass the sampled events leg; under OR, sessions
    # matched via unsampled branches (persons, cohorts, console logs) would be multiplied by the
    # correction. Without sampling the scan is full price, so bound its window instead.
    unsampled = query.operand == FilterLogicalOperator.OR_
    sample_factor = None if unsampled else _ESTIMATE_EVENTS_SAMPLE_FACTOR
    scan_window_days = budget.window_days(unsampled=unsampled)

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
        settings=HogQLGlobalSettings(max_execution_time=budget.max_execution_seconds),
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
    budget: EstimateBudget = BATCH_ESTIMATE_BUDGET,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> None:
    """Recompute and persist the scanner's projected monthly volume. Raises on failure; callers decide severity."""
    estimate = estimate_scanner_session_volume(
        team=scanner.team,
        query=scanner.recordings_query(),
        sampling_mode=scanner.sampling_mode,
        budget=budget,
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
