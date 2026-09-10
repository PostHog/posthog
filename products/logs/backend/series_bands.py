"""Per-series log volume band charts for one service, read from logs_volume_buckets.

The observed line is the caller's window of volume per (namespace, environment,
severity) series, at most MAX_WINDOW_DAYS wide. The expected band is a
time-of-week aligned min/max envelope over the BASELINE_WEEKS weeks before the
window: each display slot's band comes
from the same weekly slot in prior weeks. ClickHouse folds the baseline weeks
onto the display window; Python finishes the envelope (zero-fill, maturity
gating, widening) where the arithmetic is cheap and unit-testable.
"""

import os
import math
import time
import datetime as dt
from collections.abc import Collection
from dataclasses import replace
from typing import Literal
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import ensure_utc, relative_date_parse

WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 7
VOLUME_BUCKETS_TTL_DAYS = 42  # TTL on logs_volume_buckets, see posthog/clickhouse/hcl/sql/*/logs.sql
# The whole window has to sit inside that retention, or the observed line itself
# starts vanishing. Baseline depth thins well before this point, but a thin
# baseline is reported per series through band_ready_at and drawn as still
# learning, not rejected here.
MAX_WINDOW_START_AGE_DAYS = VOLUME_BUCKETS_TTL_DAYS - MAX_WINDOW_DAYS
BASELINE_WEEKS = 5
# Below this many full prior weeks the band rests on too little history to draw.
MIN_BASELINE_WEEKS_FOR_BAND = 2
SECONDS_PER_DAY = 24 * 3600
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY

MAX_SERIES = int(os.environ.get("LOGS_SERIES_BANDS_MAX_SERIES", "100"))
# Display grains a caller may pick. Every rung divides an hour so slots stay
# aligned with the weekly fold, and 5 is the bucket size of logs_volume_buckets.
INTERVAL_LADDER_MINUTES = (5, 15, 30, 60)
MAX_BUCKETS_PER_SERIES = int(os.environ.get("LOGS_SERIES_BANDS_MAX_BUCKETS_PER_SERIES", "500"))
# How many buckets a window aims for when the caller leaves the grain out. The
# grain snaps up to the ladder rung at or above window / BUCKET_TARGET, so a
# 7 day window keeps its hourly look and a 6 hour window reads at 5 minutes.
BUCKET_TARGET = int(os.environ.get("LOGS_SERIES_BANDS_BUCKET_TARGET", "168"))
# A series' lifetime starts at the first slot followed by sustained traffic: at
# least this fraction of the slots after it are non-empty, over the day and over
# the week. A stray row before the real start would otherwise date the lifetime
# and turn every empty week between them into a baseline of zeros.
ALIVE_SLOT_FRACTION = float(os.environ.get("LOGS_SERIES_BANDS_ALIVE_SLOT_FRACTION", "0.2"))
# A series keeps a grain only where it is dense enough to read there: at least
# ALIVE_SLOT_FRACTION of its window buckets are non-empty, and those buckets
# average at least this many records. Below that the band floor, which scales
# with the grain, sits under most observed values and nearly every bucket marks.
MIN_MEAN_PER_ALIVE_BUCKET = float(os.environ.get("LOGS_SERIES_BANDS_MIN_MEAN_PER_ALIVE_BUCKET", "5"))
# Widening keeps the envelope from reading as a hairline on quiet series: the
# fraction scales both edges, the floor lifts the upper edge by a per-hour
# count so a band exists even where every baseline week saw the same value.
BAND_WIDEN_FRACTION = 0.1
BAND_FLOOR_PER_HOUR = 2.0

# ClickHouse time one request may spend, shared across its passes. The
# coarsening walk costs one pass per rung, so a per-pass cap would let a
# request against a sparse service spend the whole cap once per rung.
MAX_EXECUTION_SECONDS = int(os.environ.get("LOGS_SERIES_BANDS_MAX_EXECUTION_SECONDS", "30"))


class SeriesBandsFetchTruncated(Exception):
    pass


class SeriesBandsWindowInvalid(Exception):
    pass


CoarsenedReason = Literal["sparse", "quiet"]


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
    history_start: dt.datetime
    band_ready_at: dt.datetime | None
    interval_minutes: int
    coarsened_reason: CoarsenedReason | None
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
class SeriesBandsWindow:
    start: dt.datetime
    end: dt.datetime
    interval_minutes: int


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


@frozen
class _SeriesRows:
    lifetime_start: dt.datetime
    slots: list[_SlotRow]


def floor_to_interval(value: dt.datetime, interval_minutes: int) -> dt.datetime:
    seconds = interval_minutes * 60
    return dt.datetime.fromtimestamp(int(value.timestamp()) // seconds * seconds, tz=dt.UTC)


def fetch_series_slot_rows(
    team: Team,
    service_name: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    interval_minutes: int,
    series_keys: Collection[_SeriesKey] | None = None,
    max_execution_seconds: int = MAX_EXECUTION_SECONDS,
) -> dict[_SeriesKey, _SeriesRows]:
    """One ClickHouse pass: interval rollup over the window plus baseline, folded
    by time-of-week onto the display window's slots, plus each series' lifetime
    start.

    Rows are sparse — a (series, slot) with no observed and no baseline data has
    no row. Missing baseline weeks are reconstructed in Python from
    baseline_samples vs the weeks the series existed. Baseline samples only
    count slots at or after the lifetime start. With series_keys the pass reads
    only those series and skips the volume ranking."""
    tag_queries(product=Product.LOGS, feature=Feature.QUERY, source="logs_series_bands", team_id=str(team.id))

    baseline_start = window_start - dt.timedelta(weeks=BASELINE_WEEKS)
    # arrayFirst yields index 0 when no run of alive_slots slots fits inside a
    # week, so a series without sustained traffic is dated from the window start
    # and reports as learning with band_ready_at ahead of the window.
    alive_slots = max(1, math.ceil(ALIVE_SLOT_FRACTION * SECONDS_PER_WEEK / (interval_minutes * 60)))
    # The week's count alone reads a few stray rows a few days ahead of a dense
    # stretch as its start, because the stretch supplies the count. Holding the
    # same fraction over the day after the slot leaves only slots that carry
    # traffic of their own.
    alive_day_slots = max(1, math.ceil(ALIVE_SLOT_FRACTION * SECONDS_PER_DAY / (interval_minutes * 60)))
    series_filter: ast.Expr
    if series_keys is None:
        # The series cap ranks over the whole 42d, not the display window: a series
        # that went silent this week has zero window volume, and ranking on the
        # window alone would drop exactly the series a silence should surface. The
        # subquery fetches one series past the cap so the caller can tell a full
        # response from a truncated one.
        series_filter = parse_select(
            """
            SELECT namespace, environment, severity_text
            FROM posthog.logs_volume_buckets
            WHERE service_name = {service_name}
                AND time_bucket >= {baseline_start}
                AND time_bucket < {window_end}
            GROUP BY namespace, environment, severity_text
            ORDER BY sum(log_count) DESC
            LIMIT {max_series_plus_probe}
            """,
            placeholders={
                "service_name": ast.Constant(value=service_name),
                "window_end": ast.Constant(value=window_end),
                "baseline_start": ast.Constant(value=baseline_start),
                "max_series_plus_probe": ast.Constant(value=MAX_SERIES + 1),
            },
        )
    else:
        series_filter = ast.Tuple(
            exprs=[
                ast.Tuple(exprs=[ast.Constant(value=part) for part in (key.namespace, key.environment, key.severity)])
                for key in series_keys
            ]
        )
    query = parse_select(
        """
        WITH slots AS (
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
                AND (namespace, environment, severity_text) IN {series_filter}
            GROUP BY namespace, environment, severity_text, slot
        ),
        lifetimes AS (
            SELECT
                namespace,
                environment,
                severity_text,
                arraySort(groupArray(toUnixTimestamp(slot))) AS slot_times,
                arrayFirst(
                    i -> i + {alive_slots} - 1 <= length(slot_times)
                        AND slot_times[i + {alive_slots} - 1] - slot_times[i] < {week_seconds}
                        AND slot_times[i + {alive_day_slots} - 1] - slot_times[i] < {day_seconds},
                    arrayEnumerate(slot_times)
                ) AS alive_index,
                if(alive_index = 0, {window_start}, toDateTime(slot_times[alive_index])) AS lifetime_start
            FROM slots
            GROUP BY namespace, environment, severity_text
        )
        SELECT
            slots.namespace AS namespace,
            slots.environment AS environment,
            slots.severity_text AS severity_text,
            {window_start} + toIntervalSecond(
                (toUnixTimestamp(slots.slot) - toUnixTimestamp({window_start}) + {baseline_seconds}) % {week_seconds}
            ) AS target_time,
            sumIf(slots.slot_count, slots.slot >= {window_start}) AS observed,
            countIf(slots.slot < {window_start} AND slots.slot >= lifetimes.lifetime_start) AS baseline_samples,
            minIf(slots.slot_count, slots.slot < {window_start} AND slots.slot >= lifetimes.lifetime_start) AS baseline_min,
            maxIf(slots.slot_count, slots.slot < {window_start} AND slots.slot >= lifetimes.lifetime_start) AS baseline_max,
            lifetimes.lifetime_start AS lifetime_start
        FROM slots
        INNER JOIN lifetimes
            ON slots.namespace = lifetimes.namespace
            AND slots.environment = lifetimes.environment
            AND slots.severity_text = lifetimes.severity_text
        GROUP BY namespace, environment, severity_text, target_time, lifetime_start
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
            "alive_slots": ast.Constant(value=alive_slots),
            "alive_day_slots": ast.Constant(value=alive_day_slots),
            "day_seconds": ast.Constant(value=SECONDS_PER_DAY),
            "series_filter": series_filter,
            "row_limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
        },
    )
    assert isinstance(query, ast.SelectQuery)

    response = execute_hogql_query(
        query_type="logs_series_bands",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=HogQLGlobalSettings(max_execution_time=max_execution_seconds),
        limit_context=LimitContext.QUERY,
        # Constants above are UTC; without this the printer emits them against
        # the project timezone and the weekly fold lands on the wrong slots.
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
    )

    if len(response.results) >= MAX_SELECT_RETURNED_ROWS:
        raise SeriesBandsFetchTruncated(f"series bands fetch returned {len(response.results)} rows, at the row limit")

    rows: dict[_SeriesKey, _SeriesRows] = {}
    for row in response.results:
        key = _SeriesKey(namespace=row[0], environment=row[1], severity=row[2])
        series = rows.get(key)
        if series is None:
            series = rows[key] = _SeriesRows(lifetime_start=ensure_utc(row[8]), slots=[])
        series.slots.append(
            _SlotRow(
                target_time=ensure_utc(row[3]),
                observed=int(row[4]),
                baseline_samples=int(row[5]),
                baseline_min=int(row[6]),
                baseline_max=int(row[7]),
            )
        )
    return rows


def _baseline_weeks_available(later: dt.datetime, lifetime_start: dt.datetime) -> int:
    """Whole weeks of series lifetime before `later`, capped at the baseline depth.

    Against the window start this is the series' maturity; against one display
    slot it is how many of that slot's weekly samples carry information. A week
    whose sample slot predates the lifetime says nothing; a week inside the
    lifetime with no row was a real zero.
    """
    weeks = int((later - lifetime_start).total_seconds()) // SECONDS_PER_WEEK
    return min(BASELINE_WEEKS, max(0, weeks))


def _band_gate(
    window_start: dt.datetime, window_end: dt.datetime, lifetime_start: dt.datetime
) -> tuple[int, dt.datetime | None]:
    """Baseline depth at the window start, and when a shallow series gains its band.

    The gate reads sustained history before window_start, so a live window must
    travel a whole window length past the lifetime threshold before a band is
    drawn. One rule returns both, so the countdown cannot drift off the gate it
    counts to.
    """
    baseline_weeks = _baseline_weeks_available(window_start, lifetime_start)
    if baseline_weeks >= MIN_BASELINE_WEEKS_FOR_BAND:
        return baseline_weeks, None
    threshold = lifetime_start + dt.timedelta(weeks=MIN_BASELINE_WEEKS_FOR_BAND)
    return baseline_weeks, threshold + (window_end - window_start)


def _build_series(
    key: _SeriesKey,
    series_rows: _SeriesRows,
    window_start: dt.datetime,
    window_end: dt.datetime,
    interval_minutes: int,
) -> BandSeries:
    by_time = {row.target_time: row for row in series_rows.slots}
    lifetime_start = series_rows.lifetime_start
    baseline_weeks, band_ready_at = _band_gate(window_start, window_end, lifetime_start)
    banded = band_ready_at is None
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
            expected = _baseline_weeks_available(slot, lifetime_start)
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
        history_start=lifetime_start,
        band_ready_at=band_ready_at,
        interval_minutes=interval_minutes,
        coarsened_reason=None,
        buckets=buckets,
    )


def _density_shortfall(series: BandSeries) -> CoarsenedReason | None:
    alive = [bucket.observed for bucket in series.buckets if bucket.observed > 0]
    if len(alive) < ALIVE_SLOT_FRACTION * len(series.buckets):
        return "sparse"
    if sum(alive) / len(alive) < MIN_MEAN_PER_ALIVE_BUCKET:
        return "quiet"
    return None


def _series_key(series: BandSeries) -> _SeriesKey:
    return _SeriesKey(namespace=series.namespace, environment=series.environment, severity=series.severity)


def _remaining_execution_seconds(deadline: float) -> int | None:
    """Whole seconds left in the request's ClickHouse budget, or None once it is spent."""
    remaining = int(deadline - time.monotonic())
    return remaining if remaining > 0 else None


def _coarsen_sparse_series(
    team: Team,
    service_name: str,
    series: list[BandSeries],
    window_start: dt.datetime,
    window_end: dt.datetime,
    interval_minutes: int,
    deadline: float,
) -> list[BandSeries]:
    """Move each series that is too sparse at the requested grain up the ladder
    to the first rung where it is dense enough, or to the top rung.

    Every rung is one ClickHouse pass scoped to the series still failing, so the
    worst case costs one pass per rung above the requested grain. The passes
    share the request's execution budget, so that worst case costs the same
    ClickHouse time as a single pass, and the walk stops at the rung reached when
    the budget runs out. Every series that fails the gate keeps the reason from
    the requested grain, because that is the grain the caller asked for and did
    not get. A series the walk cannot reach, because a rung has no rows for it
    or the budget is spent first, returns at the requested grain with that same
    reason."""
    settled: list[BandSeries] = []
    pending: dict[_SeriesKey, BandSeries] = {}
    for candidate in series:
        shortfall = _density_shortfall(candidate)
        if shortfall is None:
            settled.append(candidate)
            continue
        pending[_series_key(candidate)] = replace(candidate, coarsened_reason=shortfall)

    for rung in (rung for rung in INTERVAL_LADDER_MINUTES if rung > interval_minutes):
        if not pending:
            break
        remaining = _remaining_execution_seconds(deadline)
        if remaining is None:
            break
        rung_start = floor_to_interval(window_start, rung)
        rung_end = floor_to_interval(window_end, rung)
        rows = fetch_series_slot_rows(
            team,
            service_name,
            rung_start,
            rung_end,
            rung,
            series_keys=list(pending),
            max_execution_seconds=remaining,
        )
        still_failing: dict[_SeriesKey, BandSeries] = {}
        for key, fallback in pending.items():
            if key not in rows:
                settled.append(fallback)
                continue
            candidate = replace(
                _build_series(key, rows[key], rung_start, rung_end, rung), coarsened_reason=fallback.coarsened_reason
            )
            if _density_shortfall(candidate) is None:
                settled.append(candidate)
            else:
                still_failing[key] = candidate
        pending = still_failing

    settled.extend(pending.values())
    return settled


_UTC_ZONE = ZoneInfo("UTC")


def _parse_bound(value: str, *, now: dt.datetime) -> dt.datetime:
    # No calendar snapping here, so there is no calendar to snap in: a relative
    # bound is an offset from now and an ISO bound carries its own offset.
    return ensure_utc(relative_date_parse(value, _UTC_ZONE, now=now))


def pick_interval_minutes(window_start: dt.datetime, window_end: dt.datetime) -> int:
    """The first ladder rung at or above the step that cuts the window into BUCKET_TARGET buckets, capped at the coarsest.

    The span is measured on bounds floored to the finest rung, as the query at that rung would see them."""
    finest = INTERVAL_LADDER_MINUTES[0]
    span = floor_to_interval(window_end, finest) - floor_to_interval(window_start, finest)
    step_minutes = span.total_seconds() / 60 / BUCKET_TARGET
    return next((grain for grain in INTERVAL_LADDER_MINUTES if grain >= step_minutes), INTERVAL_LADDER_MINUTES[-1])


def resolve_window(
    date_from: str | None,
    date_to: str | None,
    *,
    interval_minutes: int | None = 60,
    now: dt.datetime | None = None,
) -> SeriesBandsWindow:
    """Turn a request date range into the snapped window to chart, defaulting to the last WINDOW_DAYS.

    Without a grain the window picks its own, aiming for BUCKET_TARGET buckets."""
    # Wall clock, never max(time_bucket): prod carries future buckets from
    # device clock skew (ingest clamps at +24h), and the exclusive window_end
    # bound is what keeps them out of the observed line.
    now = ensure_utc(now) if now is not None else dt.datetime.now(dt.UTC)

    window_end = _parse_bound(date_to, now=now) if date_to else now
    window_end = min(window_end, now)
    window_start = _parse_bound(date_from, now=now) if date_from else window_end - dt.timedelta(days=WINDOW_DAYS)
    if interval_minutes is None:
        interval_minutes = pick_interval_minutes(window_start, window_end)
    # Snapping can move either bound by up to one interval, so every check runs
    # on the snapped values the query will actually see.
    window_start = floor_to_interval(window_start, interval_minutes)
    window_end = floor_to_interval(window_end, interval_minutes)

    if window_end < window_start:
        raise SeriesBandsWindowInvalid("date_to must be after date_from.")
    if window_end == window_start:
        raise SeriesBandsWindowInvalid(
            f"The window is empty at the {interval_minutes} minute grain. Pick a range that covers at least one bucket."
        )
    if window_end - window_start > dt.timedelta(days=MAX_WINDOW_DAYS):
        raise SeriesBandsWindowInvalid(f"The window may span at most {MAX_WINDOW_DAYS} days.")
    if now - window_start > dt.timedelta(days=MAX_WINDOW_START_AGE_DAYS):
        raise SeriesBandsWindowInvalid(
            f"Log volume history does not reach that far back. The window may start at most "
            f"{MAX_WINDOW_START_AGE_DAYS} days ago."
        )
    _check_bucket_cap(window_start, window_end, interval_minutes)

    return SeriesBandsWindow(start=window_start, end=window_end, interval_minutes=interval_minutes)


def _bucket_count(window_start: dt.datetime, window_end: dt.datetime, interval_minutes: int) -> int:
    return int((window_end - window_start).total_seconds()) // (interval_minutes * 60)


def _check_bucket_cap(window_start: dt.datetime, window_end: dt.datetime, interval_minutes: int) -> None:
    buckets = _bucket_count(window_start, window_end, interval_minutes)
    if buckets <= MAX_BUCKETS_PER_SERIES:
        return
    fitting = next(
        (
            grain
            for grain in INTERVAL_LADDER_MINUTES
            if _bucket_count(window_start, window_end, grain) <= MAX_BUCKETS_PER_SERIES
        ),
        None,
    )
    remedy = f"Use a {fitting} minute grain or a shorter window." if fitting else "Pick a shorter window."
    raise SeriesBandsWindowInvalid(
        f"The window spans {buckets} buckets at the {interval_minutes} minute grain, "
        f"over the cap of {MAX_BUCKETS_PER_SERIES} buckets per series. {remedy}"
    )


def run_series_bands(
    team: Team,
    service_name: str,
    *,
    window_start: dt.datetime,
    window_end: dt.datetime,
    interval_minutes: int = 60,
) -> SeriesBandsResult:
    window_start = floor_to_interval(window_start, interval_minutes)
    window_end = floor_to_interval(window_end, interval_minutes)

    deadline = time.monotonic() + MAX_EXECUTION_SECONDS
    slot_rows = fetch_series_slot_rows(team, service_name, window_start, window_end, interval_minutes)
    series = [_build_series(key, rows, window_start, window_end, interval_minutes) for key, rows in slot_rows.items()]
    series.sort(key=lambda s: (-s.total_count, s.namespace, s.environment, s.severity))
    series_truncated = len(series) > MAX_SERIES
    series = _coarsen_sparse_series(
        team, service_name, series[:MAX_SERIES], window_start, window_end, interval_minutes, deadline
    )
    series.sort(key=lambda s: (-s.total_count, s.namespace, s.environment, s.severity))

    return SeriesBandsResult(
        service_name=service_name,
        window_start=window_start,
        window_end=window_end,
        interval_minutes=interval_minutes,
        series_truncated=series_truncated,
        series=series,
    )
