"""Just-in-time anomaly scan over the log volume rollup.

Runs the APM anomaly detector (imported via the APM facade) synchronously
over one service's log volume for a caller-chosen evaluation window. This is
the validation surface for the detector — no scheduled evaluation, no
persisted issues. Everything is computed per request.

Cost model: ``logs_volume_buckets`` already holds contiguous 5-minute counts
per series, so one aggregation over the lookback replaces the raw-log scan and
its time-of-week slicing. A single per-scan byte budget is enforced
ClickHouse-side (``max_bytes_to_read`` + throw); a scan that still exceeds it
fails rather than degrading, because the rollup leaves nothing cheap to fall
back to.

Level adjustment is disabled here: the reference window in the slow level
component is not time-of-week matched, so a stationary series with a weekly
shape gets a level factor that tracks the shape instead of the level. Enabling
it needs a detector change first.
"""

import os
import datetime as dt
from dataclasses import dataclass, field, replace
from enum import StrEnum
from zoneinfo import ZoneInfo

import numpy as np
from prometheus_client import Counter

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Team

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
    evaluate_issue_transition,
    evaluate_series_bucket_detail,
    fingerprint_for,
    required_consecutive,
)
from products.logs.backend.series_bands import MAX_SERIES
from products.logs.backend.volume_rollup import FINALIZATION_ALLOWANCE, VOLUME_BUCKETS_TTL_DAYS

BUCKET = dt.timedelta(minutes=BUCKET_MINUTES)

MAX_EVAL_DAYS = 7

# Per-scan ClickHouse read budget. A rollup aggregation over one service stays
# far below this; the budget is the hard stop for a service whose series count
# or lookback makes the read unexpectedly large.
SCAN_MAX_BYTES_TO_READ = int(os.environ.get("LOGS_ANOMALY_SCAN_MAX_BYTES_TO_READ", str(10 * 1024**3)))
# Baseline lookback. It stops a week short of the rollup's TTL floor: a
# six-week lookback sits exactly on that floor, so it is never reachable and
# every scan would report a truncated baseline. Five weeks is also what the
# volume chart fits its bands on.
SCAN_LOOKBACK_WEEKS = int(os.environ.get("LOGS_ANOMALY_SCAN_LOOKBACK_WEEKS", "5"))
# Wall-clock deadline for the ClickHouse read.
SCAN_MAX_EXECUTION_SECONDS = int(os.environ.get("LOGS_ANOMALY_SCAN_MAX_EXECUTION_SECONDS", "60"))
# Detector replay costs one evaluation per series per evaluated bucket, and the
# whole scan is one synchronous request. This ceiling holds the replay near ten
# seconds; past it the quietest series are dropped, the same way the chart's
# series cap drops them.
SCAN_MAX_BUCKET_EVALUATIONS = int(os.environ.get("LOGS_ANOMALY_SCAN_MAX_BUCKET_EVALUATIONS", "25000"))

# Scan outcomes, so the failure rate is a number the team can read rather than
# one inferred from MCP tool errors.
SCAN_OUTCOMES = Counter(
    "logs_anomaly_scan_outcomes_total",
    "On-demand log anomaly scans by outcome",
    labelnames=["outcome"],
)


class ScanBudgetExceeded(Exception):
    """The rollup read blew the byte budget or the scan deadline."""


class ScanWindowInvalid(Exception):
    """The requested evaluation window cannot be scanned."""


class BindingConstraint(StrEnum):
    """What limited the scan's baseline, scan-wide."""

    ROLLUP_DEPTH = "rollup_depth"


class SeriesLimit(StrEnum):
    """What limited one series' baseline maturity."""

    # First data appears well inside the lookback: the series is younger than
    # the lookback, or older rows were dropped by a per-stream retention rule.
    # ClickHouse cannot distinguish the two.
    SERIES_HISTORY = "series_history"
    ROLLUP_DEPTH = "rollup_depth"


@dataclass(frozen=True, kw_only=True)
class ScanWindow:
    eval_start: dt.datetime
    eval_end: dt.datetime


@dataclass(frozen=True, kw_only=True)
class RollupSeries:
    namespace: str
    environment: str
    severity: str
    counts: dict[dt.datetime, int]


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
    namespace: str
    environment: str
    severity: str
    stage: BaselineStage | None
    tier: TrafficTier | None
    history_start: dt.datetime | None
    limited_by: SeriesLimit | None
    buckets: list[ScanBucket]


@dataclass(frozen=True, kw_only=True)
class ScanIssue:
    namespace: str
    environment: str
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
    binding_constraints: list[BindingConstraint]
    series_truncated: bool
    series: list[ScanSeries]
    issues: list[ScanIssue]

    @property
    def lookback_days(self) -> float:
        return self.lookback_buckets / BUCKETS_PER_DAY


def floor_to_bucket(value: dt.datetime) -> dt.datetime:
    value = value.astimezone(dt.UTC)
    return value.replace(minute=value.minute - value.minute % BUCKET_MINUTES, second=0, microsecond=0)


def latest_scannable_end(now: dt.datetime) -> dt.datetime:
    """Exclusive end of the newest bucket the rollup has finished counting.

    The volume tick only writes a bucket once it has been closed for
    FINALIZATION_ALLOWANCE, so a window that runs up to the wall clock ends in
    buckets that are still filling and read as a drop."""
    return floor_to_bucket(now - FINALIZATION_ALLOWANCE)


def resolve_eval_window(
    date_from: dt.datetime,
    date_to: dt.datetime,
    now: dt.datetime | None = None,
) -> ScanWindow:
    """Snap a requested window to the 5-minute grid and to what the rollup holds."""
    now = floor_to_bucket(now or dt.datetime.now(dt.UTC))
    eval_start = floor_to_bucket(date_from)
    eval_end = min(floor_to_bucket(date_to), latest_scannable_end(now))

    if eval_end <= eval_start:
        raise ScanWindowInvalid(
            "The evaluation window is empty. Its end is clamped to the newest bucket the volume rollup "
            f"has finished counting, about {int(FINALIZATION_ALLOWANCE.total_seconds() // 60)} minutes ago."
        )
    if eval_end - eval_start > dt.timedelta(days=MAX_EVAL_DAYS):
        raise ScanWindowInvalid(f"The evaluation window may span at most {MAX_EVAL_DAYS} days.")
    if now - eval_start > dt.timedelta(days=VOLUME_BUCKETS_TTL_DAYS):
        raise ScanWindowInvalid(
            f"Log volume history does not reach that far back. The window may start at most "
            f"{VOLUME_BUCKETS_TTL_DAYS} days ago."
        )
    return ScanWindow(eval_start=eval_start, eval_end=eval_end)


def _scan_settings(max_execution_seconds: int) -> HogQLGlobalSettings:
    return HogQLGlobalSettings(
        max_execution_time=max_execution_seconds,
        max_bytes_to_read=SCAN_MAX_BYTES_TO_READ,
        read_overflow_mode="throw",
    )


def fetch_series_counts(
    team: Team,
    service_name: str,
    fetch_start: dt.datetime,
    fetch_end: dt.datetime,
    series_cap: int = MAX_SERIES,
    max_execution_seconds: int = SCAN_MAX_EXECUTION_SECONDS,
) -> tuple[list[RollupSeries], bool]:
    """Contiguous 5-minute counts per series for one service over [fetch_start, fetch_end).

    One row per series rather than per bucket: a five-week lookback holds more
    buckets than the HogQL row limit allows, so the buckets ride along as an
    array. Returns the series ordered by volume, plus whether the service has
    more of them than series_cap."""
    tag_queries(product=Product.LOGS, feature=Feature.QUERY, source="logs_anomaly_scan", team_id=str(team.id))

    query = parse_select(
        """
        WITH buckets AS (
            SELECT
                namespace,
                environment,
                lower(severity_text) AS severity,
                time_bucket,
                sum(log_count) AS count
            FROM posthog.logs_volume_buckets
            WHERE service_name = {service_name}
                AND time_bucket >= {fetch_start}
                AND time_bucket < {fetch_end}
            GROUP BY namespace, environment, severity, time_bucket
        )
        SELECT
            namespace,
            environment,
            severity,
            sum(count) AS total,
            groupArray(tuple(toUnixTimestamp(time_bucket), count)) AS series_counts
        FROM buckets
        GROUP BY namespace, environment, severity
        ORDER BY total DESC
        LIMIT {max_series_plus_probe}
        """,
        placeholders={
            "service_name": ast.Constant(value=service_name),
            "fetch_start": ast.Constant(value=fetch_start),
            "fetch_end": ast.Constant(value=fetch_end),
            # One past the cap, so a full response is distinguishable from a truncated one.
            "max_series_plus_probe": ast.Constant(value=series_cap + 1),
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

    series = [
        RollupSeries(
            namespace=row[0],
            environment=row[1],
            severity=row[2] or "unknown",
            counts={dt.datetime.fromtimestamp(bucket_ts, tz=dt.UTC): count for bucket_ts, count in row[4]},
        )
        for row in response.results
    ]
    return series[:series_cap], len(series) > series_cap


def _jit_config(lookback_buckets: int) -> DetectionConfig:
    return replace(
        DetectionConfig.from_env(),
        max_lookback_buckets=lookback_buckets,
        level_adjustment_enabled=False,
    )


def resolve_lookback_buckets(
    eval_start: dt.datetime,
    eval_end: dt.datetime,
    now: dt.datetime,
    config: DetectionConfig,
) -> tuple[int, bool]:
    """Baseline buckets to fetch before eval_start, and whether the rollup's depth cut them short.

    Two caps beyond the configured lookback. The rollup only keeps
    VOLUME_BUCKETS_TTL_DAYS of buckets. And the whole grid stays under the
    developing-to-mature switch: the mature pool draws fewer samples than the
    developing pool it replaces, so a series that crosses the switch gets a
    noisier band, not a better one."""
    eval_buckets = int((eval_end - eval_start) / BUCKET)
    wanted = min(
        SCAN_LOOKBACK_WEEKS * BUCKETS_PER_WEEK,
        max(config.developing_until_buckets - eval_buckets, 0),
    )
    rollup_floor = now - dt.timedelta(days=VOLUME_BUCKETS_TTL_DAYS)
    depth = max(int((eval_start - rollup_floor) / BUCKET), 0)
    return min(wanted, depth), depth < wanted


def resolve_series_cap(eval_start: dt.datetime, eval_end: dt.datetime) -> int:
    """How many series one scan can afford to replay over this window.

    The chart's cap is the ceiling. A wide window buys fewer series, because the
    replay pays for every series over every evaluated bucket."""
    eval_buckets = max(int((eval_end - eval_start) / BUCKET), 1)
    return max(1, min(MAX_SERIES, SCAN_MAX_BUCKET_EVALUATIONS // eval_buckets))


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
    if BindingConstraint.ROLLUP_DEPTH in scan_constraints:
        return SeriesLimit.ROLLUP_DEPTH
    return None


def _replay(
    rollup_series: list[RollupSeries],
    eval_start: dt.datetime,
    eval_end: dt.datetime,
    lookback_buckets: int,
    service_name: str,
    config: DetectionConfig,
    tz: ZoneInfo,
    scan_constraints: list[BindingConstraint],
) -> tuple[list[ScanSeries], list[ScanIssue]]:
    grid_start = eval_start - lookback_buckets * BUCKET
    n_buckets = int((eval_end - grid_start) / BUCKET)
    eval_start_index = int((eval_start - grid_start) / BUCKET)
    grid = TimeGrid.build(grid_start, n_buckets, tz)
    band_model = NegativeBinomialBandModel()

    keys = [
        SeriesKey(
            namespace=rollup.namespace,
            service=service_name,
            environment=rollup.environment,
            severity=rollup.severity,
        )
        for rollup in rollup_series
    ]
    histories: dict[SeriesKey, SeriesHistory] = {}
    for key, rollup in zip(keys, rollup_series):
        counts = np.zeros(n_buckets, dtype=np.float64)
        for bucket_time, total in rollup.counts.items():
            index = int((bucket_time - grid_start) / BUCKET)
            if 0 <= index < n_buckets:
                counts[index] = total
        histories[key] = SeriesHistory(grid_start=grid_start, counts=counts)

    series_buckets: dict[SeriesKey, list[ScanBucket]] = {key: [] for key in histories}
    last_stage: dict[SeriesKey, BaselineStage | None] = dict.fromkeys(histories)
    last_tier: dict[SeriesKey, TrafficTier | None] = dict.fromkeys(histories)
    accumulators: dict[IssueFingerprint, _IssueAccumulator] = {}

    for index in range(eval_start_index, n_buckets):
        bucket_time = grid_start + index * BUCKET
        tick_verdicts: dict[IssueFingerprint, BucketVerdict] = {}
        for key, history in histories.items():
            evaluation = evaluate_series_bucket_detail(history, index, key, grid, config, band_model)
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
            series_buckets[key].append(
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
                last_stage[key] = evaluation.stage
            if evaluation.tier is not None:
                last_tier[key] = evaluation.tier

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
    for key in sorted(histories, key=lambda k: (k.namespace, k.environment, k.severity)):
        first = histories[key].first_active_index
        history_start = histories[key].bucket_time(first) if first is not None else None
        series.append(
            ScanSeries(
                namespace=key.namespace,
                environment=key.environment,
                severity=key.severity,
                stage=last_stage[key],
                tier=last_tier[key],
                history_start=history_start,
                limited_by=_series_limit(history_start, grid_start, scan_constraints),
                buckets=series_buckets[key],
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
                namespace=accumulator.fingerprint.namespace,
                environment=accumulator.fingerprint.environment,
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
    """Read the rollup, replay the detector over it, and assemble the result.

    Caller has already resolved the window with ``resolve_eval_window``."""
    now = floor_to_bucket(now or dt.datetime.now(dt.UTC))
    eval_start = floor_to_bucket(eval_start)
    eval_end = min(floor_to_bucket(eval_end), latest_scannable_end(now))

    config_probe = _jit_config(1)
    lookback_buckets, depth_limited = resolve_lookback_buckets(eval_start, eval_end, now, config_probe)

    try:
        rollup_series, series_truncated = fetch_series_counts(
            team,
            service_name,
            eval_start - lookback_buckets * BUCKET,
            eval_end,
            series_cap=resolve_series_cap(eval_start, eval_end),
        )
    except (CHQueryErrorTooManyBytes, ClickHouseQueryTimeOut) as err:
        SCAN_OUTCOMES.labels(outcome="too_expensive").inc()
        raise ScanBudgetExceeded(
            f"Anomaly scan for service {service_name!r} exceeded its read budget or time limit"
        ) from err

    constraints = [BindingConstraint.ROLLUP_DEPTH] if depth_limited else []
    series, issues = _replay(
        rollup_series,
        eval_start,
        eval_end,
        lookback_buckets,
        service_name,
        _jit_config(lookback_buckets or 1),
        ZoneInfo(team.timezone),
        constraints,
    )
    SCAN_OUTCOMES.labels(outcome="ok").inc()
    return ScanResult(
        service_name=service_name,
        eval_start=eval_start,
        eval_end=eval_end,
        lookback_buckets=lookback_buckets,
        binding_constraints=constraints,
        series_truncated=series_truncated,
        series=series,
        issues=issues,
    )
