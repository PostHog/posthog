"""Per-series log volume band charts for one service, read from logs_volume_buckets.

The observed line is the last WINDOW_DAYS of volume per (namespace, environment,
severity) series. The expected band is a time-of-week aligned min/max envelope
over the BASELINE_WEEKS weeks before the window: each display slot's band comes
from the same weekly slot in prior weeks. ClickHouse folds the baseline weeks
onto the display window; Python finishes the envelope (zero-fill, maturity
gating, widening) where the arithmetic is cheap and unit-testable.
"""

import os
import datetime as dt

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import ensure_utc

WINDOW_DAYS = 7
BASELINE_WEEKS = 5
# Below this many full prior weeks the band rests on too little history to draw.
MIN_BASELINE_WEEKS_FOR_BAND = 2
SECONDS_PER_WEEK = 7 * 24 * 3600

MAX_SERIES = int(os.environ.get("LOGS_SERIES_BANDS_MAX_SERIES", "100"))
# Widening keeps the envelope from reading as a hairline on quiet series: the
# fraction scales both edges, the floor lifts the upper edge by a per-hour
# count so a band exists even where every baseline week saw the same value.
BAND_WIDEN_FRACTION = 0.1
BAND_FLOOR_PER_HOUR = 2.0

MAX_EXECUTION_SECONDS = int(os.environ.get("LOGS_SERIES_BANDS_MAX_EXECUTION_SECONDS", "30"))


class SeriesBandsFetchTruncated(Exception):
    pass


@frozen
class BandBucket:
    time: dt.datetime
    observed: int
    lower: float | None
    upper: float | None


@frozen
class BandSeries:
    namespace: str
    environment: str
    severity: str
    total_count: int
    baseline_weeks: int
    buckets: list[BandBucket]


@frozen
class SeriesBandsResult:
    service_name: str
    window_start: dt.datetime
    window_end: dt.datetime
    interval_minutes: int
    series_truncated: bool
    series: list[BandSeries]


@frozen
class _SeriesKey:
    namespace: str
    environment: str
    severity: str


@frozen
class _SlotRow:
    target_time: dt.datetime
    observed: int
    baseline_samples: int
    baseline_min: int
    baseline_max: int
    earliest_slot: dt.datetime


def floor_to_interval(value: dt.datetime, interval_minutes: int) -> dt.datetime:
    seconds = interval_minutes * 60
    return dt.datetime.fromtimestamp(int(value.timestamp()) // seconds * seconds, tz=dt.UTC)


def fetch_series_slot_rows(
    team: Team,
    service_name: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    interval_minutes: int,
) -> dict[_SeriesKey, list[_SlotRow]]:
    """One ClickHouse pass: hourly rollup over the window plus baseline, folded
    by time-of-week onto the display window's slots.

    Rows are sparse — a (series, slot) with no observed and no baseline data has
    no row. Missing baseline weeks are reconstructed in Python from
    baseline_samples vs the weeks the series existed."""
    tag_queries(product=Product.LOGS, feature=Feature.QUERY, source="logs_series_bands", team_id=str(team.id))

    baseline_start = window_start - dt.timedelta(weeks=BASELINE_WEEKS)
    # The series cap ranks over the whole 42d, not the display window: a series
    # that went silent this week has zero window volume, and ranking on the
    # window alone would drop exactly the series a silence should surface. The
    # subquery fetches one series past the cap so the caller can tell a full
    # response from a truncated one.
    query = parse_select(
        """
        SELECT
            namespace,
            environment,
            severity_text,
            {window_start} + toIntervalSecond(
                (toUnixTimestamp(slot) - toUnixTimestamp({window_start}) + {baseline_seconds}) % {week_seconds}
            ) AS target_time,
            sumIf(slot_count, slot >= {window_start}) AS observed,
            countIf(slot < {window_start}) AS baseline_samples,
            minIf(slot_count, slot < {window_start}) AS baseline_min,
            maxIf(slot_count, slot < {window_start}) AS baseline_max,
            min(slot) AS earliest_slot
        FROM (
            SELECT
                namespace,
                environment,
                severity_text,
                toStartOfInterval(time_bucket, {interval}, 'UTC') AS slot,
                sum(log_count) AS slot_count
            FROM posthog.logs_volume_buckets
            WHERE service_name = {service_name}
                AND time_bucket >= {baseline_start}
                AND time_bucket < {window_end}
                AND (namespace, environment, severity_text) IN (
                    SELECT namespace, environment, severity_text
                    FROM posthog.logs_volume_buckets
                    WHERE service_name = {service_name}
                        AND time_bucket >= {baseline_start}
                        AND time_bucket < {window_end}
                    GROUP BY namespace, environment, severity_text
                    ORDER BY sum(log_count) DESC
                    LIMIT {max_series_plus_probe}
                )
            GROUP BY namespace, environment, severity_text, slot
        )
        GROUP BY namespace, environment, severity_text, target_time
        LIMIT {row_limit}
        """,
        placeholders={
            "service_name": ast.Constant(value=service_name),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "baseline_start": ast.Constant(value=baseline_start),
            "interval": ast.Call(name="toIntervalMinute", args=[ast.Constant(value=interval_minutes)]),
            "baseline_seconds": ast.Constant(value=BASELINE_WEEKS * SECONDS_PER_WEEK),
            "week_seconds": ast.Constant(value=SECONDS_PER_WEEK),
            "max_series_plus_probe": ast.Constant(value=MAX_SERIES + 1),
            "row_limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
        },
    )
    assert isinstance(query, ast.SelectQuery)

    response = execute_hogql_query(
        query_type="logs_series_bands",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_SECONDS),
        limit_context=LimitContext.QUERY,
        # Constants above are UTC; without this the printer emits them against
        # the project timezone and the weekly fold lands on the wrong slots.
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
    )

    if len(response.results) >= MAX_SELECT_RETURNED_ROWS:
        raise SeriesBandsFetchTruncated(f"series bands fetch returned {len(response.results)} rows, at the row limit")

    rows: dict[_SeriesKey, list[_SlotRow]] = {}
    for row in response.results:
        key = _SeriesKey(namespace=row[0], environment=row[1], severity=row[2])
        rows.setdefault(key, []).append(
            _SlotRow(
                target_time=ensure_utc(row[3]),
                observed=int(row[4]),
                baseline_samples=int(row[5]),
                baseline_min=int(row[6]),
                baseline_max=int(row[7]),
                earliest_slot=ensure_utc(row[8]),
            )
        )
    return rows


def _baseline_weeks_available(later: dt.datetime, earliest_slot: dt.datetime) -> int:
    """Whole weeks of series lifetime before `later`, capped at the baseline depth.

    Against the window start this is the series' maturity; against one display
    slot it is how many of that slot's weekly samples carry information. A week
    whose sample slot predates the series says nothing; a week inside the
    lifetime with no row was a real zero.
    """
    weeks = int((later - earliest_slot).total_seconds()) // SECONDS_PER_WEEK
    return min(BASELINE_WEEKS, max(0, weeks))


def _build_series(
    key: _SeriesKey,
    slot_rows: list[_SlotRow],
    window_start: dt.datetime,
    window_end: dt.datetime,
    interval_minutes: int,
) -> BandSeries:
    by_time = {row.target_time: row for row in slot_rows}
    earliest_slot = min(row.earliest_slot for row in slot_rows)
    baseline_weeks = _baseline_weeks_available(window_start, earliest_slot)
    banded = baseline_weeks >= MIN_BASELINE_WEEKS_FOR_BAND
    floor = BAND_FLOOR_PER_HOUR * interval_minutes / 60

    buckets: list[BandBucket] = []
    total_count = 0
    step = dt.timedelta(minutes=interval_minutes)
    slot = window_start
    while slot < window_end:
        row = by_time.get(slot)
        observed = row.observed if row else 0
        total_count += observed
        lower: float | None = None
        upper: float | None = None
        if banded:
            # Every slot sits at or after window_start, so a banded series has at
            # least MIN_BASELINE_WEEKS_FOR_BAND samples to expect at every slot.
            expected = _baseline_weeks_available(slot, earliest_slot)
            samples = row.baseline_samples if row else 0
            # A lifetime week with no row at this slot was a real zero, so any
            # missing sample drags the envelope floor to zero.
            low = row.baseline_min if row and samples >= expected else 0
            high = row.baseline_max if row else 0
            lower = low * (1 - BAND_WIDEN_FRACTION)
            upper = high * (1 + BAND_WIDEN_FRACTION) + floor
        buckets.append(BandBucket(time=slot, observed=observed, lower=lower, upper=upper))
        slot += step

    return BandSeries(
        namespace=key.namespace,
        environment=key.environment,
        severity=key.severity,
        total_count=total_count,
        baseline_weeks=baseline_weeks,
        buckets=buckets,
    )


def run_series_bands(
    team: Team,
    service_name: str,
    interval_minutes: int = 60,
    now: dt.datetime | None = None,
) -> SeriesBandsResult:
    # Wall clock, never max(time_bucket): prod carries future buckets from
    # device clock skew (ingest clamps at +24h), and the exclusive window_end
    # bound is what keeps them out of the observed line.
    now = now or dt.datetime.now(dt.UTC)
    window_end = floor_to_interval(now, interval_minutes)
    window_start = window_end - dt.timedelta(days=WINDOW_DAYS)

    slot_rows = fetch_series_slot_rows(team, service_name, window_start, window_end, interval_minutes)
    series = [_build_series(key, rows, window_start, window_end, interval_minutes) for key, rows in slot_rows.items()]
    series.sort(key=lambda s: (-s.total_count, s.namespace, s.environment, s.severity))
    series_truncated = len(series) > MAX_SERIES
    series = series[:MAX_SERIES]

    return SeriesBandsResult(
        service_name=service_name,
        window_start=window_start,
        window_end=window_end,
        interval_minutes=interval_minutes,
        series_truncated=series_truncated,
        series=series,
    )
