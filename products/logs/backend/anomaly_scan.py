"""Just-in-time anomaly scan over raw logs.

Runs the APM anomaly detector (imported via the APM facade) synchronously
over one service's log volume for a caller-chosen evaluation window. This is
the validation surface for the detector — no rollup table, no scheduled
evaluation, no persisted issues. Everything is computed per request.

Cost model: baselines only ever sample specific time-of-week/time-of-day
slices, so the ClickHouse query fetches those slices as explicit timestamp
ranges instead of a contiguous lookback scan. A per-scan byte budget is
enforced ClickHouse-side (``max_bytes_to_read`` + throw); on overflow the
scan degrades — shorter lookback (capping how mature baselines can get),
then a clipped evaluation window — and reports what bound it.

Level adjustment is disabled here: the slow level component compares the
recent mean against the full contiguous baseline window, which a slice-pruned
fetch cannot supply. The rollup-backed path keeps it.
"""

import os
import time
import datetime as dt
from dataclasses import dataclass, field, replace
from enum import StrEnum
from zoneinfo import ZoneInfo

import numpy as np

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Team
from posthog.models.team.logs_retention import DEFAULT_LOGS_RETENTION_DAYS

from products.apm.backend.facade.api import (
    BUCKET_MINUTES,
    BUCKETS_PER_DAY,
    BUCKETS_PER_WEEK,
    BaselineStage,
    BucketVerdict,
    DetectionConfig,
    Direction,
    IssueAction,
    IssueFingerprint,
    IssueSnapshot,
    IssueState,
    NegativeBinomialBandModel,
    SeriesHistory,
    SeriesKey,
    TimeGrid,
    TrafficTier,
    VerdictType,
    candidate_slice_pad_buckets,
    evaluate_issue_transition,
    evaluate_series_bucket_detail,
    fingerprint_for,
    required_consecutive,
)

BUCKET = dt.timedelta(minutes=BUCKET_MINUTES)

MAX_EVAL_DAYS = 7

# Per-scan ClickHouse read budget. The projection-shaped aggregation usually
# stays far below this; the budget is the hard stop for services whose filters
# fall back to raw scans.
SCAN_MAX_BYTES_TO_READ = int(os.environ.get("LOGS_ANOMALY_SCAN_MAX_BYTES_TO_READ", str(10 * 1024**3)))
# Mature-entry lookback. 6 weeks is the measured cost/precision sweet spot for
# on-demand scans; the rollup path uses a longer window.
SCAN_LOOKBACK_WEEKS = int(os.environ.get("LOGS_ANOMALY_SCAN_LOOKBACK_WEEKS", "6"))
# Wall-clock deadline for the whole scan, shared across degradation attempts —
# a retrying ladder must not multiply the per-request resource spend.
SCAN_MAX_EXECUTION_SECONDS = int(os.environ.get("LOGS_ANOMALY_SCAN_MAX_EXECUTION_SECONDS", "60"))


class ScanBudgetExceeded(Exception):
    """Every degradation rung blew the byte budget or the scan deadline."""


class ScanFetchTruncated(Exception):
    """The bucket fetch hit its row limit, so the history would be silently
    incomplete. Degradable: fewer lookback buckets means fewer rows."""


class BindingConstraint(StrEnum):
    """What limited the scan's baseline, scan-wide."""

    TEAM_RETENTION = "team_retention"
    BYTE_BUDGET = "byte_budget"


class SeriesLimit(StrEnum):
    """What limited one series' baseline maturity."""

    # First data appears well inside the lookback: the series is younger than
    # the lookback, or older rows were dropped by a per-stream retention rule.
    # ClickHouse cannot distinguish the two.
    SERIES_HISTORY = "series_history"
    BYTE_BUDGET = "byte_budget"
    TEAM_RETENTION = "team_retention"


@dataclass(frozen=True, kw_only=True)
class TimeRange:
    """Half-open [start, end) range, both ends aligned to the 5-minute grid."""

    start: dt.datetime
    end: dt.datetime


@dataclass(frozen=True, kw_only=True)
class ScanAttempt:
    lookback_buckets: int
    eval_start: dt.datetime
    eval_end: dt.datetime
    eval_clipped: bool


@dataclass(frozen=True, kw_only=True)
class ScanBucket:
    time: dt.datetime
    observed: float
    expected: float | None
    lower: float | None
    upper: float | None
    stage: BaselineStage | None
    verdict: VerdictType | None


@dataclass(frozen=True, kw_only=True)
class ScanSeries:
    severity: str
    stage: BaselineStage | None
    tier: TrafficTier | None
    history_start: dt.datetime | None
    limited_by: SeriesLimit | None
    buckets: list[ScanBucket]


@dataclass(frozen=True, kw_only=True)
class ScanIssue:
    direction: Direction
    severity: str | None
    kind: VerdictType
    state: IssueState
    opened_at: dt.datetime
    last_anomalous_at: dt.datetime
    resolved_at: dt.datetime | None
    anomalous_bucket_times: list[dt.datetime]


@dataclass(frozen=True, kw_only=True)
class ScanResult:
    service_name: str
    eval_start: dt.datetime
    eval_end: dt.datetime
    lookback_buckets: int
    eval_clipped: bool
    degraded: bool
    binding_constraints: list[BindingConstraint]
    series: list[ScanSeries]
    issues: list[ScanIssue]

    @property
    def lookback_days(self) -> float:
        return self.lookback_buckets / BUCKETS_PER_DAY


def floor_to_bucket(value: dt.datetime) -> dt.datetime:
    value = value.astimezone(dt.UTC)
    return value.replace(minute=value.minute - value.minute % BUCKET_MINUTES, second=0, microsecond=0)


def merge_ranges(ranges: list[TimeRange]) -> list[TimeRange]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: r.start)
    merged = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        if current.start <= last.end:
            if current.end > last.end:
                merged[-1] = TimeRange(start=last.start, end=current.end)
        else:
            merged.append(current)
    return merged


def baseline_slice_ranges(
    eval_start: dt.datetime,
    eval_end: dt.datetime,
    lookback_buckets: int,
    config: DetectionConfig,
) -> list[TimeRange]:
    """Every timestamp range the detector can sample when evaluating
    [eval_start, eval_end): the eval window plus a gate pre-pad, daily-stepped
    slices for cold-start pools, and weekly-stepped slices for developing and
    mature pools. Overlaps merged; nothing before eval_start - lookback."""
    fetch_floor = eval_start - lookback_buckets * BUCKET

    gate_pad_buckets = max(
        config.persistence_window_buckets,
        config.expiry_buckets,
        config.traffic_floor_window_buckets,
        config.baseline_guard_buckets,
    )
    ranges = [TimeRange(start=eval_start - gate_pad_buckets * BUCKET, end=eval_end)]

    pad = candidate_slice_pad_buckets(config) * BUCKET
    cold_days = config.cold_start_until_buckets // BUCKETS_PER_DAY
    for day in range(1, cold_days + 1):
        offset = dt.timedelta(days=day)
        ranges.append(TimeRange(start=eval_start - offset - pad, end=eval_end - offset + pad))
    for week in range(1, lookback_buckets // BUCKETS_PER_WEEK + 1):
        offset = dt.timedelta(weeks=week)
        ranges.append(TimeRange(start=eval_start - offset - pad, end=eval_end - offset + pad))

    clamped = [TimeRange(start=max(r.start, fetch_floor), end=r.end) for r in ranges if r.end > fetch_floor]
    return merge_ranges(clamped)


def degradation_ladder(eval_start: dt.datetime, eval_end: dt.datetime, full_lookback_buckets: int) -> list[ScanAttempt]:
    """Attempts in cost order: full lookback first, then progressively less
    history (capping baseline maturity), finally a clipped eval window."""
    lookback_rungs = [
        full_lookback_buckets,
        3 * BUCKETS_PER_WEEK,
        2 * BUCKETS_PER_WEEK,
        4 * BUCKETS_PER_DAY,
    ]
    attempts: list[ScanAttempt] = []
    seen: set[int] = set()
    for lookback in lookback_rungs:
        lookback = min(lookback, full_lookback_buckets)
        if lookback in seen:
            continue
        seen.add(lookback)
        attempts.append(
            ScanAttempt(lookback_buckets=lookback, eval_start=eval_start, eval_end=eval_end, eval_clipped=False)
        )

    min_lookback = min(seen)
    for clip in (dt.timedelta(hours=24), dt.timedelta(hours=6), dt.timedelta(hours=1)):
        clipped_start = max(eval_start, eval_end - clip)
        if clipped_start > eval_start:
            attempts.append(
                ScanAttempt(
                    lookback_buckets=min_lookback, eval_start=clipped_start, eval_end=eval_end, eval_clipped=True
                )
            )
    return attempts


def _scan_settings(max_execution_seconds: int) -> HogQLGlobalSettings:
    return HogQLGlobalSettings(
        max_execution_time=max_execution_seconds,
        max_bytes_to_read=SCAN_MAX_BYTES_TO_READ,
        read_overflow_mode="throw",
    )


def _covered_days(ranges: list[TimeRange]) -> list[dt.date]:
    days: set[dt.date] = set()
    for r in ranges:
        day = r.start.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        while day < r.end:
            days.add(day.date())
            day += dt.timedelta(days=1)
    return sorted(days)


def fetch_bucket_counts(
    team: Team,
    service_name: str,
    ranges: list[TimeRange],
    max_execution_seconds: int = SCAN_MAX_EXECUTION_SECONDS,
) -> dict[str, dict[dt.datetime, int]]:
    """5-minute bucket counts per severity for one service, restricted to the
    given timestamp ranges. Raises CHQueryErrorTooManyBytes past the budget."""
    tag_queries(product=Product.LOGS, feature=Feature.QUERY, source="logs_anomaly_scan", team_id=str(team.id))

    range_exprs: list[ast.Expr] = [
        parse_expr(
            "timestamp >= {start} AND timestamp < {end}",
            placeholders={"start": ast.Constant(value=r.start), "end": ast.Constant(value=r.end)},
        )
        for r in ranges
    ]
    # Day-level primary-key pruning: the logs table sorts on time_bucket
    # (day-truncated). Pin the truncation to UTC — convertToProjectTimezone is
    # off, so the constants are UTC and an unpinned toStartOfDay would compare
    # against server-local day boundaries. Both sides must be Date: HogQL
    # prints datetime constants as DateTime64, and ClickHouse's IN section
    # refuses to coerce DateTime64 elements against a DateTime left side
    # (ordered comparisons coerce; IN does not).
    day_prune = parse_expr(
        "toDate(toStartOfDay(time_bucket, 'UTC')) IN {days}",
        placeholders={"days": ast.Tuple(exprs=[ast.Constant(value=day) for day in _covered_days(ranges)])},
    )
    where = ast.And(
        exprs=[
            day_prune,
            parse_expr("service_name = {service}", placeholders={"service": ast.Constant(value=service_name)}),
            ast.Or(exprs=range_exprs) if len(range_exprs) > 1 else range_exprs[0],
        ]
    )

    # toStartOfMinute lets ClickHouse serve the aggregation from the
    # minute-grained counts projection instead of raw rows — same trick as
    # AlertCheckQuery.execute_bucketed.
    query = parse_select(
        """
        SELECT
            toStartOfInterval(toStartOfMinute(timestamp), toIntervalMinute({bucket_minutes})) AS bucket,
            severity_text,
            count() AS total
        FROM logs
        WHERE {where}
        GROUP BY bucket, severity_text
        ORDER BY bucket ASC
        LIMIT {row_limit}
        """,
        placeholders={
            "bucket_minutes": ast.Constant(value=BUCKET_MINUTES),
            "where": where,
            # Without an explicit LIMIT, HogQL applies the context default of
            # 100 rows, and ClickHouse returns buckets in primary-key order —
            # the scan would silently see only the oldest sliver of history.
            "row_limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
        },
    )
    assert isinstance(query, ast.SelectQuery)

    response = execute_hogql_query(
        query_type="logs_anomaly_scan",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=_scan_settings(max_execution_seconds),
        limit_context=LimitContext.QUERY,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
    )

    # A full page may be complete-but-exactly-full; treating it as truncated is
    # the conservative read — degrading beats scoring against partial history.
    if len(response.results) >= MAX_SELECT_RETURNED_ROWS:
        raise ScanFetchTruncated(f"bucket fetch returned {len(response.results)} rows, at the row limit")

    counts: dict[str, dict[dt.datetime, int]] = {}
    for row in response.results:
        bucket_time, severity, total = row[0], row[1] or "unknown", row[2]
        if bucket_time.tzinfo is None:
            bucket_time = bucket_time.replace(tzinfo=dt.UTC)
        counts.setdefault(severity, {})[bucket_time] = total
    return counts


def _jit_config(lookback_buckets: int) -> DetectionConfig:
    return replace(
        DetectionConfig.from_env(),
        max_lookback_buckets=lookback_buckets,
        level_adjustment_enabled=False,
    )


@dataclass(kw_only=True)
class _IssueAccumulator:
    fingerprint: IssueFingerprint
    snapshot: IssueSnapshot | None
    opened_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None
    anomalous_times: list[dt.datetime] = field(default_factory=list)
    ever_opened: bool = False
    last_kind: VerdictType | None = None


def _series_limit(
    history_start: dt.datetime | None,
    grid_start: dt.datetime,
    scan_constraints: list[BindingConstraint],
) -> SeriesLimit | None:
    if history_start is not None and history_start > grid_start + dt.timedelta(days=1):
        return SeriesLimit.SERIES_HISTORY
    if BindingConstraint.BYTE_BUDGET in scan_constraints:
        return SeriesLimit.BYTE_BUDGET
    if BindingConstraint.TEAM_RETENTION in scan_constraints:
        return SeriesLimit.TEAM_RETENTION
    return None


def _replay(
    counts_by_severity: dict[str, dict[dt.datetime, int]],
    attempt: ScanAttempt,
    service_name: str,
    config: DetectionConfig,
    tz: ZoneInfo,
    scan_constraints: list[BindingConstraint],
) -> tuple[list[ScanSeries], list[ScanIssue]]:
    grid_start = attempt.eval_start - attempt.lookback_buckets * BUCKET
    n_buckets = int((attempt.eval_end - grid_start) / BUCKET)
    eval_start_index = int((attempt.eval_start - grid_start) / BUCKET)
    grid = TimeGrid.build(grid_start, n_buckets, tz)
    band_model = NegativeBinomialBandModel()

    histories: dict[str, SeriesHistory] = {}
    for severity, per_bucket in counts_by_severity.items():
        counts = np.zeros(n_buckets, dtype=np.float64)
        for bucket_time, total in per_bucket.items():
            index = int((bucket_time - grid_start) / BUCKET)
            if 0 <= index < n_buckets:
                counts[index] = total
        histories[severity] = SeriesHistory(grid_start=grid_start, counts=counts)

    series_keys = {
        severity: SeriesKey(namespace="logs", service=service_name, environment="", severity=severity)
        for severity in histories
    }
    series_buckets: dict[str, list[ScanBucket]] = {severity: [] for severity in histories}
    last_stage: dict[str, BaselineStage | None] = dict.fromkeys(histories)
    last_tier: dict[str, TrafficTier | None] = dict.fromkeys(histories)
    accumulators: dict[IssueFingerprint, _IssueAccumulator] = {}

    for index in range(eval_start_index, n_buckets):
        bucket_time = grid_start + index * BUCKET
        tick_verdicts: dict[IssueFingerprint, BucketVerdict] = {}
        for severity, history in histories.items():
            evaluation = evaluate_series_bucket_detail(history, index, series_keys[severity], grid, config, band_model)
            verdict = evaluation.verdict
            if verdict is not None:
                # Exclusion feedback: flagged buckets never legitimize
                # themselves in later baselines.
                history.excluded.add(index)
                fingerprint = fingerprint_for(verdict.key, verdict.verdict_type)
                existing = tick_verdicts.get(fingerprint)
                # Direction-shared fingerprints (drop/silence): silence wins the tick.
                if existing is None or verdict.verdict_type is VerdictType.SILENCE:
                    tick_verdicts[fingerprint] = verdict
            series_buckets[severity].append(
                ScanBucket(
                    time=bucket_time,
                    observed=evaluation.observed,
                    expected=evaluation.band.expected if evaluation.band else None,
                    lower=evaluation.band.lower if evaluation.band else None,
                    upper=evaluation.band.upper if evaluation.band else None,
                    stage=evaluation.stage,
                    verdict=verdict.verdict_type if verdict else None,
                )
            )
            if evaluation.stage is not None:
                last_stage[severity] = evaluation.stage
            if evaluation.tier is not None:
                last_tier[severity] = evaluation.tier

        open_fingerprints = {fp for fp, acc in accumulators.items() if acc.snapshot is not None}
        for fingerprint in open_fingerprints | set(tick_verdicts):
            verdict_here = tick_verdicts.get(fingerprint)
            accumulator = accumulators.get(fingerprint)
            snapshot = accumulator.snapshot if accumulator else None
            if verdict_here is not None:
                required = required_consecutive(verdict_here.verdict_type, verdict_here.tier, config)
                outcome = evaluate_issue_transition(snapshot, verdict_here.verdict_type, index, required, config)
            else:
                outcome = evaluate_issue_transition(snapshot, None, index, config.open_after_buckets, config)

            if accumulator is None:
                accumulator = _IssueAccumulator(fingerprint=fingerprint, snapshot=outcome.snapshot)
                accumulators[fingerprint] = accumulator
            else:
                accumulator.snapshot = outcome.snapshot
            if verdict_here is not None:
                accumulator.anomalous_times.append(bucket_time)
            if outcome.snapshot is not None:
                accumulator.last_kind = outcome.snapshot.kind
            if outcome.action in (IssueAction.OPEN, IssueAction.REOPEN):
                accumulator.ever_opened = True
                if accumulator.opened_at is None:
                    accumulator.opened_at = bucket_time
                accumulator.resolved_at = None
            elif outcome.action is IssueAction.RESOLVE:
                accumulator.resolved_at = bucket_time

    series = []
    for severity in sorted(histories):
        first = histories[severity].first_active_index
        history_start = histories[severity].bucket_time(first) if first is not None else None
        series.append(
            ScanSeries(
                severity=severity,
                stage=last_stage[severity],
                tier=last_tier[severity],
                history_start=history_start,
                limited_by=_series_limit(history_start, grid_start, scan_constraints),
                buckets=series_buckets[severity],
            )
        )

    issues = []
    for accumulator in accumulators.values():
        if not accumulator.ever_opened or accumulator.opened_at is None or accumulator.last_kind is None:
            continue
        snapshot = accumulator.snapshot
        # A resolved issue's evidence ends at its resolution: sub-threshold blips
        # inside the reopen window that never cleared the bar are not part of it,
        # so they must not push last_anomalous_at past resolved_at. A reopen
        # clears resolved_at, so an active issue keeps its full evidence.
        resolved_at = accumulator.resolved_at
        anomalous_times = accumulator.anomalous_times
        if resolved_at is not None:
            anomalous_times = [t for t in anomalous_times if t <= resolved_at]
        issues.append(
            ScanIssue(
                direction=accumulator.fingerprint.direction,
                severity=accumulator.fingerprint.severity,
                kind=snapshot.kind if snapshot is not None else accumulator.last_kind,
                # A None snapshot after an open means a post-resolution blip fizzled.
                state=snapshot.state if snapshot is not None else IssueState.RESOLVED,
                opened_at=accumulator.opened_at,
                last_anomalous_at=anomalous_times[-1],
                resolved_at=resolved_at,
                anomalous_bucket_times=anomalous_times,
            )
        )
    issues.sort(key=lambda issue: issue.opened_at)
    return series, issues


def run_scan(
    team: Team,
    service_name: str,
    eval_start: dt.datetime,
    eval_end: dt.datetime,
    now: dt.datetime | None = None,
) -> ScanResult:
    """Fetch, degrade if needed, replay the detector, and assemble the result.

    Caller has already validated the window (aligned, ordered, ≤ MAX_EVAL_DAYS,
    clamped to now)."""
    now = floor_to_bucket(now or dt.datetime.now(dt.UTC))
    eval_start = floor_to_bucket(eval_start)
    eval_end = min(floor_to_bucket(eval_end), now)

    retention_days = (team.logs_settings or {}).get("retention_days", DEFAULT_LOGS_RETENTION_DAYS)
    retention_floor = now - dt.timedelta(days=retention_days)
    requested_lookback = SCAN_LOOKBACK_WEEKS * BUCKETS_PER_WEEK
    retention_lookback = max(int((eval_start - retention_floor) / BUCKET), 0)
    full_lookback = min(requested_lookback, retention_lookback)
    retention_limited = full_lookback < requested_lookback

    config_probe = _jit_config(full_lookback or 1)

    deadline = time.monotonic() + SCAN_MAX_EXECUTION_SECONDS
    last_error: Exception | None = None
    for attempt in degradation_ladder(eval_start, eval_end, max(full_lookback, 1)):
        remaining_seconds = int(deadline - time.monotonic())
        if remaining_seconds <= 0:
            break
        ranges = baseline_slice_ranges(attempt.eval_start, attempt.eval_end, attempt.lookback_buckets, config_probe)
        try:
            counts = fetch_bucket_counts(team, service_name, ranges, max_execution_seconds=remaining_seconds)
        except (CHQueryErrorTooManyBytes, ClickHouseQueryTimeOut, ScanFetchTruncated) as err:
            last_error = err
            continue

        degraded = attempt.lookback_buckets < max(full_lookback, 1) or attempt.eval_clipped
        constraints: list[BindingConstraint] = []
        if degraded:
            constraints.append(BindingConstraint.BYTE_BUDGET)
        if retention_limited:
            constraints.append(BindingConstraint.TEAM_RETENTION)

        config = _jit_config(attempt.lookback_buckets)
        series, issues = _replay(counts, attempt, service_name, config, ZoneInfo(team.timezone), constraints)
        return ScanResult(
            service_name=service_name,
            eval_start=attempt.eval_start,
            eval_end=attempt.eval_end,
            lookback_buckets=attempt.lookback_buckets,
            eval_clipped=attempt.eval_clipped,
            degraded=degraded,
            binding_constraints=constraints,
            series=series,
            issues=issues,
        )

    raise ScanBudgetExceeded(
        f"Anomaly scan for service {service_name!r} exceeded its read budget or deadline at every degradation rung"
    ) from last_error
