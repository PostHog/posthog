import datetime as dt
from dataclasses import dataclass

from django.utils import timezone

from posthog.schema import FilterLogicalOperator, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Team, User
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, SamplingMode
from products.replay_vision.backend.queries.scanner_candidate_query import (
    eligibility_predicates,
    surfacing_score_predicate,
)

# The estimate always projects to a calendar month.
ESTIMATE_WINDOW_DAYS = 30
# Fallback sample rate for events subqueries; matched counts are corrected back up.
_ESTIMATE_EVENTS_SAMPLE_FACTOR = 0.1
_EXACT_ATTEMPT_BUDGET_FRACTION = 0.5


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

# Persisted per-scanner estimates older than this are recomputed by the refresher. Estimates only
# track data drift between edits (an edit nulls `estimated_at` and refreshes within one cycle), so a
# slower clock trades projection freshness directly for ClickHouse reads.
ESTIMATE_STALE_AFTER = dt.timedelta(hours=72)
# Disabled scanners refresh on a slower clock still: fresh enough that re-enabling one puts a usable
# number into the quota sum, without paying a full-price estimate for every parked scanner.
DISABLED_ESTIMATE_STALE_AFTER = dt.timedelta(days=7)


@dataclass(frozen=True)
class ScannerVolumeEstimate:
    matched_sessions: int
    # May be smaller than the scan window when the team has fewer days of recordings.
    effective_window_days: int
    sampled: bool = False


@dataclass(frozen=True)
class _EstimateQueryPlan:
    combined_query: ast.SelectQuery
    sampled: bool


def estimate_scanner_session_volume(
    *,
    team: Team,
    query: RecordingsQuery,
    user: User | None = None,
    sampling_mode: SamplingMode | str = SamplingMode.COMPREHENSIVE,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
    budget: EstimateBudget = BATCH_ESTIMATE_BUDGET,
) -> ScannerVolumeEstimate:
    """Count sessions matching `query` over a recent window, for the scanner cost preview.

    Reuses `SessionRecordingListFromQuery`'s filter compilation so the estimate and the real
    recordings list agree on what "matches". The exact count runs first; when it times out, is
    rejected as too slow, or hits a memory limit, it retries with sampled events subqueries and
    corrects the count back up (`sampled=True` on the result).

    `user` is the principal the experiment_exposure filter's access check runs as. With no
    principal (a genuinely userless caller, or a scanner whose creator was deleted) the exposure
    filter is dropped and the broader eligible set counted — an over-count is the safe direction
    for a budget forecast.
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

    sampled_plan = _plan_estimate_query(
        team=team,
        query=windowed,
        user=user,
        sampling_mode=sampling_mode,
        sample_factor=sample_factor,
        scan_window_days=scan_window_days,
        now=now,
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    if not sampled_plan.sampled:
        # Nothing was sampled, so a fallback would rerun the identical query.
        return _execute_estimate_query(
            sampled_plan,
            team=team,
            query_type="ReplayVisionScannerEstimateQuery",
            max_execution_seconds=budget.max_execution_seconds,
            scan_window_days=scan_window_days,
            ch_user=ch_user,
        )

    exact_plan = _plan_estimate_query(
        team=team,
        query=windowed,
        user=user,
        sampling_mode=sampling_mode,
        sample_factor=None,
        scan_window_days=scan_window_days,
        now=now,
    )
    exact_budget = max(1, round(budget.max_execution_seconds * _EXACT_ATTEMPT_BUDGET_FRACTION))
    try:
        return _execute_estimate_query(
            exact_plan,
            team=team,
            query_type="ReplayVisionScannerEstimateExactQuery",
            max_execution_seconds=exact_budget,
            scan_window_days=scan_window_days,
            ch_user=ch_user,
        )
    except (
        ClickHouseQueryTimeOut,
        ClickHouseEstimatedQueryExecutionTimeTooLong,
        ClickHouseQueryMemoryLimitExceeded,
    ):
        # Full budget: halving it fails teams whose sampled count needs more than half.
        return _execute_estimate_query(
            sampled_plan,
            team=team,
            query_type="ReplayVisionScannerEstimateSampledQuery",
            max_execution_seconds=budget.max_execution_seconds,
            scan_window_days=scan_window_days,
            ch_user=ch_user,
        )


def _plan_estimate_query(
    *,
    team: Team,
    query: RecordingsQuery,
    user: User | None,
    sampling_mode: SamplingMode | str,
    sample_factor: float | None,
    scan_window_days: int,
    now: dt.datetime,
) -> _EstimateQueryPlan:
    # Count only sessions the sweep would actually observe, so the forecast matches the eligible set the candidate query selects.
    extra_having = eligibility_predicates()
    if (surfacing := surfacing_score_predicate(sampling_mode)) is not None:
        extra_having.append(surfacing)
    # Without a principal the experiment_exposure access check would raise, so drop the filter and
    # count the broader eligible set: an over-count is the safe direction for a budget forecast.
    # Callers that have a principal keep the filter and get the real, narrowed count.
    estimate_query = query
    if query.experiment_exposure is not None and user is None:
        estimate_query = query.model_copy(deep=True)
        estimate_query.experiment_exposure = None
    list_query = SessionRecordingListFromQuery(
        team=team,
        query=estimate_query,
        user=user,
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
    return _EstimateQueryPlan(combined_query=combined_query, sampled=list_query.events_subqueries_sampled)


def _execute_estimate_query(
    plan: _EstimateQueryPlan,
    *,
    team: Team,
    query_type: str,
    max_execution_seconds: int,
    scan_window_days: int,
    ch_user: ClickHouseUser,
) -> ScannerVolumeEstimate:
    response = execute_hogql_query(
        query=plan.combined_query,
        team=team,
        query_type=query_type,
        # "throw" so a timeout raises instead of returning a partial count as exact.
        settings=HogQLGlobalSettings(max_execution_time=max_execution_seconds, timeout_overflow_mode="throw"),
        ch_user=ch_user,
    )
    results = response.results or []
    matched = int(results[0][0]) if results else 0
    if plan.sampled:
        matched = round(matched / _ESTIMATE_EVENTS_SAMPLE_FACTOR)
    earliest = results[0][1] if results else None

    return ScannerVolumeEstimate(
        matched_sessions=matched,
        effective_window_days=_clamp_window_days(earliest, scan_window_days),
        sampled=plan.sampled,
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
    # Scoped, not tag_queries: a bare tag on the worker thread would leak onto later queries and
    # charge other scanners' reads to this one in the meter. Previews stay untagged (no scanner yet).
    with tags_context(scanner_id=str(scanner.pk)):
        estimate = estimate_scanner_session_volume(
            team=scanner.team,
            query=scanner.targeted_recordings_query(),
            # The refresher has no request; the creator is the same principal the sweep scans as.
            user=scanner.created_by,
            sampling_mode=scanner.sampling_mode,
            budget=budget,
            ch_user=ch_user,
        )
    projection = project_monthly_observations(estimate, scanner.sampling_rate)
    estimated_at = timezone.now()
    # Filtered write so a config edit racing the (slow) estimate query can't get stamped fresh with stale numbers.
    # JSONField quirk: `field=None` filters for JSON null, not SQL NULL, so the no-targeting case needs isnull.
    updated = ReplayScanner.objects.filter(
        pk=scanner.pk,
        query=scanner.query,
        sampling_rate=scanner.sampling_rate,
        sampling_mode=scanner.sampling_mode,
        **(
            {"experiment_targeting__isnull": True}
            if scanner.experiment_targeting is None
            else {"experiment_targeting": scanner.experiment_targeting}
        ),
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
