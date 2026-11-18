"""Incremental refresh of metrics dashboard tiles.

A tile whose window ends now keeps its cached points before a cut, queries only the newest slice,
and splices that slice in. The cut sits `RECOMPUTE_WINDOW` before the cached window's end, so the
buckets that can still receive samples are always queried again. A full run every `FULL_RUN_EVERY`
picks up samples that land later than that.
"""

import math
import random
import datetime as dt
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar
from zoneinfo import ZoneInfo

from django.conf import settings

import structlog
from pydantic import BaseModel

from posthog.schema import MetricsHistogramQueryResponse, MetricsQueryPoint, MetricsQuerySeries

from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import CACHE_ENTRY_FRESHNESS_KEY

from products.metrics.backend.metric_query_runner import (
    MAX_RAW_SERIES,
    _align_to_interval,
    _interval_step,
    counter_lookback,
)

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

RECOMPUTE_WINDOW = dt.timedelta(minutes=5)
FULL_RUN_EVERY = dt.timedelta(minutes=15)

_STATE_KEY = "metrics_tail"

R = TypeVar("R", bound=BaseModel)


class FullRunReason(StrEnum):
    NO_CACHED_RESULT = "no_cached_result"
    INTERVAL_CHANGED = "interval_changed"
    PERIODIC_FULL_RUN = "periodic_full_run"
    COARSE_INTERVAL = "coarse_interval"
    WINDOW_MOVED = "window_moved"
    MERGE_REFUSED = "merge_refused"


@frozen
class TailState:
    """What a cached result covers, stored with the cache entry."""

    date_from: dt.datetime
    date_to: dt.datetime
    interval: str
    full_at: dt.datetime

    def to_record(self) -> dict[str, str]:
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "interval": self.interval,
            "full_at": self.full_at.isoformat(),
        }

    @classmethod
    def from_record(cls, record: Any) -> Optional["TailState"]:
        if not isinstance(record, dict) or not isinstance(record.get(_STATE_KEY), dict):
            return None
        state = record[_STATE_KEY]
        try:
            return cls(
                date_from=dt.datetime.fromisoformat(state["date_from"]),
                date_to=dt.datetime.fromisoformat(state["date_to"]),
                interval=str(state["interval"]),
                full_at=dt.datetime.fromisoformat(state["full_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@frozen
class TailPlan:
    cut: dt.datetime
    fetch_from: dt.datetime


def plan_tail(
    previous: TailState | None,
    *,
    date_from: dt.datetime,
    date_to: dt.datetime,
    interval: str,
    now: dt.datetime,
    tzinfo: ZoneInfo,
) -> TailPlan | FullRunReason:
    """Where the cached points stop being kept (`cut`) and where the tail query starts (`fetch_from`).

    The tail query starts `ceil((lookback + 2 * step) / step)` steps before the cut, so a rate at the
    cut has the predecessor samples that a full run gives it. Its points before the cut are dropped.
    """
    if previous is None:
        return FullRunReason.NO_CACHED_RESULT
    if previous.interval != interval:
        return FullRunReason.INTERVAL_CHANGED
    if now - previous.full_at > FULL_RUN_EVERY:
        return FullRunReason.PERIODIC_FULL_RUN
    step = _interval_step(interval)
    # Day and week buckets follow local midnight, so a DST change makes their length vary.
    if step >= dt.timedelta(days=1):
        return FullRunReason.COARSE_INTERVAL
    cut = _align_to_interval(previous.date_to - RECOMPUTE_WINDOW, interval, tzinfo=tzinfo)
    fetch_from = cut - math.ceil((counter_lookback(interval) + 2 * step) / step) * step
    if previous.date_from > date_from or date_to < previous.date_to or fetch_from <= date_from:
        return FullRunReason.WINDOW_MOVED
    return TailPlan(cut=cut, fetch_from=fetch_from)


@frozen
class SeriesKey:
    """Identifies one series across a cached result and a tail result. Hashable, so it keys dicts."""

    clause: str | None
    metric_name: str | None
    labels: tuple[tuple[str, str], ...]

    @classmethod
    def of(cls, series: MetricsQuerySeries) -> "SeriesKey":
        return cls(clause=series.clause, metric_name=series.metricName, labels=tuple(sorted(series.labels.items())))


def _magnitude(series: MetricsQuerySeries) -> float:
    return sum(abs(point.value) for point in series.points if point.value is not None)


def merge_series(
    cached: Sequence[MetricsQuerySeries],
    tail: Sequence[MetricsQuerySeries],
    *,
    start: dt.datetime,
    cut: dt.datetime,
    clause_order: Sequence[str],
    formula: bool,
) -> list[MetricsQuerySeries] | None:
    """Cached points in [start, cut) and tail points from the cut, on the grid a full run returns.

    Returns None when a full run could answer differently from the splice.
    """
    # An empty result is one series without points, which a full run with data does not return.
    if any(not series.points for series in [*cached, *tail]):
        return None
    cached_by_key = {SeriesKey.of(series): series for series in cached}
    tail_by_key = {SeriesKey.of(series): series for series in tail}
    if len(cached_by_key) != len(cached) or len(tail_by_key) != len(tail):
        return None
    # A clause at the cap keeps the largest series over the whole window, which the splice cannot rank.
    for side in (cached, tail):
        clauses = [series.clause for series in side]
        if any(clauses.count(clause) >= MAX_RAW_SERIES for clause in set(clauses)):
            return None
    # A formula series missing on one side would need the formula of zero-filled inputs there.
    if formula and cached_by_key.keys() != tail_by_key.keys():
        return None
    if any(
        cached_by_key[key].histogramBounds != series.histogramBounds
        for key, series in tail_by_key.items()
        if key in cached_by_key
    ):
        return None

    grid: dict[dt.datetime, str] = {}
    values: dict[SeriesKey, dict[dt.datetime, float | None]] = {}
    for key, series in cached_by_key.items():
        kept = values.setdefault(key, {})
        for point in series.points:
            time = dt.datetime.fromisoformat(point.time)
            if start <= time < cut:
                kept[time] = point.value
                grid.setdefault(time, point.time)
        # Zero-filled points cannot be told from observed zeros. A series with nothing else left in the
        # window was most likely seen only in the part that moved out, so a full run would not return it.
        if key not in tail_by_key and all(not value for value in kept.values()):
            del values[key]
    for key, series in tail_by_key.items():
        fresh = values.setdefault(key, {})
        for point in series.points:
            time = dt.datetime.fromisoformat(point.time)
            if time >= cut:
                fresh[time] = point.value
                grid.setdefault(time, point.time)

    times = sorted(grid)
    merged: list[MetricsQuerySeries] = []
    for key, by_time in values.items():
        source = tail_by_key.get(key) or cached_by_key[key]
        merged.append(
            source.model_copy(
                update={"points": [MetricsQueryPoint(time=grid[time], value=by_time.get(time, 0.0)) for time in times]}
            )
        )
    if formula:
        return sorted(merged, key=lambda series: tuple(sorted(series.labels.items())))
    # A full run lists clauses in request order and ranks each clause's series by magnitude.
    rank = {clause: index for index, clause in enumerate(clause_order)}
    return sorted(
        merged,
        key=lambda series: (
            rank.get(series.clause or "", len(rank)),
            -_magnitude(series),
            tuple(sorted(series.labels.items())),
        ),
    )


def merge_grid(
    cached: MetricsHistogramQueryResponse,
    tail: MetricsHistogramQueryResponse,
    *,
    start: dt.datetime,
    cut: dt.datetime,
) -> MetricsHistogramQueryResponse | None:
    """Cached heatmap columns in [start, cut) and tail columns from the cut.

    Returns None when the bucket edges differ, because every column is re-binned onto the union of edges.
    """
    if cached.bounds != tail.bounds or len(cached.counts) != len(tail.counts):
        return None
    cached_columns = [i for i, time in enumerate(cached.times) if start <= dt.datetime.fromisoformat(time) < cut]
    tail_columns = [i for i, time in enumerate(tail.times) if dt.datetime.fromisoformat(time) >= cut]
    if not cached_columns or dt.datetime.fromisoformat(cached.times[cached_columns[0]]) != start:
        return None
    return MetricsHistogramQueryResponse(
        results=None,
        times=[cached.times[i] for i in cached_columns] + [tail.times[i] for i in tail_columns],
        bounds=cached.bounds,
        counts=[
            [cached_row[i] for i in cached_columns] + [tail_row[i] for i in tail_columns]
            for cached_row, tail_row in zip(cached.counts, tail.counts)
        ],
    )


def first_difference(merged: Any, full: Any, path: str = "") -> str | None:
    """Where two dumped responses differ, with floats compared to a relative tolerance."""
    if isinstance(merged, float) and isinstance(full, float):
        return None if math.isclose(merged, full, rel_tol=1e-9, abs_tol=1e-12) else f"{path}: {merged} != {full}"
    if isinstance(merged, dict) and isinstance(full, dict):
        if merged.keys() != full.keys():
            return f"{path}: keys differ"
        for key in merged:
            difference = first_difference(merged[key], full[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(merged, list) and isinstance(full, list):
        if len(merged) != len(full):
            return f"{path}: {len(merged)} items != {len(full)}"
        for index, (left, right) in enumerate(zip(merged, full)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return None
    return None if merged == full else f"{path}: {merged!r} != {full!r}"


class TailRefresh(Generic[R]):
    """One blocking refresh of a tile: plans the tail, runs it or a full run, and records what happened."""

    def __init__(self, previous_entry: dict[str, Any] | None, *, team: "Team") -> None:
        self._previous_entry = previous_entry
        self._previous = (
            TailState.from_record(previous_entry.get(CACHE_ENTRY_FRESHNESS_KEY)) if previous_entry else None
        )
        self._team = team
        self._state: TailState | None = None
        self._mode: str | None = None
        self._full_reason: FullRunReason | None = None
        self._verify: str | None = None

    def run(
        self,
        *,
        response_type: type[R],
        date_from: dt.datetime,
        date_to: dt.datetime,
        interval: str,
        calculate: Callable[[dt.datetime], R],
        merge: Callable[[R, R, dt.datetime, dt.datetime], R | None],
    ) -> R:
        """`calculate` runs the query from a start; `merge` splices (cached, tail, start, cut)."""
        tzinfo = self._team.timezone_info
        now = dt.datetime.now(dt.UTC)
        plan = plan_tail(
            self._previous, date_from=date_from, date_to=date_to, interval=interval, now=now, tzinfo=tzinfo
        )
        if isinstance(plan, TailPlan):
            assert self._previous is not None
            merged = self._merge(response_type, merge, calculate(plan.fetch_from), date_from, interval, plan.cut)
            if merged is None:
                plan = FullRunReason.MERGE_REFUSED
            else:
                self._mode = "tail"
                if random.random() >= settings.METRICS_TAIL_REFRESH_VERIFY_RATE:
                    self._state = TailState(
                        date_from=date_from, date_to=date_to, interval=interval, full_at=self._previous.full_at
                    )
                    return merged
                # A full run is the correct answer whatever the check finds, so the refresh serves it.
                full = calculate(date_from)
                self._check(merged, full)
                self._state = TailState(date_from=date_from, date_to=date_to, interval=interval, full_at=now)
                return full
        self._mode = "full"
        self._full_reason = plan
        full = calculate(date_from)
        self._state = TailState(date_from=date_from, date_to=date_to, interval=interval, full_at=now)
        return full

    def _merge(
        self,
        response_type: type[R],
        merge: Callable[[R, R, dt.datetime, dt.datetime], R | None],
        tail: R,
        date_from: dt.datetime,
        interval: str,
        cut: dt.datetime,
    ) -> R | None:
        try:
            cached = response_type.model_validate(self._previous_entry, extra="ignore")
        except ValueError:
            return None
        start = _align_to_interval(date_from, interval, tzinfo=self._team.timezone_info)
        return merge(cached, tail, start, cut)

    def _check(self, merged: R, full: R) -> None:
        difference = first_difference(merged.model_dump(), full.model_dump())
        self._verify = "match" if difference is None else "mismatch"
        if difference is not None:
            logger.warning("metrics_tail_refresh_mismatch", team_id=self._team.pk, difference=difference[:500])

    def entry_record(self) -> dict[str, Any] | None:
        return {_STATE_KEY: self._state.to_record()} if self._state else None

    def event_properties(self) -> dict[str, Any]:
        properties = {
            "metrics_refresh": self._mode,
            "metrics_full_reason": self._full_reason.value if self._full_reason else None,
            "metrics_tail_verify": self._verify,
        }
        return {key: value for key, value in properties.items() if value is not None}


class TailRefreshMixin:
    """Wires `TailRefresh` into a metrics query runner's blocking calculation and cache entry."""

    team: "Team"
    _tail: TailRefresh[Any] | None = None

    def _tail_refresh_enabled(self, dashboard_id: int | None) -> bool:
        raise NotImplementedError()

    def _prepare_blocking_calculation(
        self, *, dashboard_id: int | None, previous_entry: Callable[[], dict[str, Any] | None]
    ) -> None:
        self._tail = TailRefresh(previous_entry(), team=self.team) if self._tail_refresh_enabled(dashboard_id) else None

    def _cache_entry_with_freshness(self, response: dict[str, Any]) -> dict[str, Any]:
        record = self._tail.entry_record() if self._tail else None
        return {**response, CACHE_ENTRY_FRESHNESS_KEY: record} if record else response

    def _staleness_event_properties(self) -> dict[str, Any]:
        properties: dict[str, Any] = super()._staleness_event_properties()  # type: ignore[misc]
        return {**properties, **self._tail.event_properties()} if self._tail else properties
