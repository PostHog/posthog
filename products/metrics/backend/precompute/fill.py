"""The fill loop: keeps each precomputed metric's hourly buckets stored, forward, back, and corrected.

Each pass over a team runs one query at a time through the ordinary metrics query runner, at an hourly
interval grouped by the kept labels. Forward fills store the hours that have settled since the last pass and
re-read the newest stored hours, so late samples replace what was stored and widen the settle delay. When
nothing is due forward, the pass backfills one day, newest first, until the retention window is covered.
A fill that returns too many rows is split in half, down to one hour, and saves the halves it finished
before the pass deadline.
"""

import math
import time
import datetime as dt
from typing import Any

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricGroupBy, MetricQueryTooManyRowsError
from products.metrics.backend.facade.enums import PrecomputedMetricKind
from products.metrics.backend.metric_query_runner import _finite_or_none
from products.metrics.backend.metric_samples_query_runner import build_metric_query_runner
from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import labels_of
from products.metrics.backend.precompute.store import HOUR, Entry, EntryKey, merge_entries, read_entries, write_entries

logger = structlog.get_logger(__name__)

# Covers the longest range a query allows (31 days) plus the first bucket's alignment.
RETENTION = dt.timedelta(days=32)
BACKFILL_STEP = dt.timedelta(days=1)
MAX_FORWARD_STEP = dt.timedelta(days=1)
REREAD = dt.timedelta(hours=2)
MAX_SETTLE_SECONDS = 2 * 60 * 60
UNUSED_AFTER = dt.timedelta(days=14)
PAUSE_AFTER_FAILURES = 10
PASS_BUDGET = dt.timedelta(minutes=4)
_LOCK_TIMEOUT_SECONDS = 10 * 60
_RELATIVE_TOLERANCE = 1e-9


class TooManySeriesError(Exception):
    pass


def _floor_hour(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)


def _hour_of(value: Any) -> dt.datetime:
    return (dt.datetime.fromisoformat(value) if isinstance(value, str) else value).astimezone(dt.UTC)


def whole_hour_offset(team: Team, *moments: dt.datetime) -> bool:
    """Hourly UTC buckets tile the project's buckets only when its UTC offset is whole hours."""
    return all(
        (moment.astimezone(team.timezone_info).utcoffset() or dt.timedelta()) % HOUR == dt.timedelta()
        for moment in moments
    )


def _query_hours(
    team: Team, precomputed_metric: MetricPrecomputedMetric, start: dt.datetime, end: dt.datetime
) -> dict[EntryKey, Entry]:
    labels = labels_of(precomputed_metric)
    kind = PrecomputedMetricKind(precomputed_metric.kind)
    histogram = kind == PrecomputedMetricKind.HISTOGRAM
    runner = build_metric_query_runner(
        team=team,
        metric_name=precomputed_metric.metric_name,
        aggregation="histogram_quantile" if histogram else kind.value,
        date_from=start,
        date_to=end,
        group_by=tuple(MetricGroupBy(key=label.key, scope=label.scope) for label in labels),
        interval="hour",
        quantile=0.5 if histogram else None,
        metric_type=precomputed_metric.metric_type or None,
    )
    entries: dict[EntryKey, Entry] = {}
    if histogram:
        group_count = len(labels)
        for row in runner.histogram_rows():
            entry = Entry(
                labels=tuple(str(value) for value in row[1 : 1 + group_count]),
                metric_type=row[4 + group_count],
                bounds=tuple(float(bound) for bound in row[1 + group_count]),
                fingerprints=set(row[3 + group_count]),
                points={_hour_of(row[0]): [float(count) for count in row[2 + group_count]]},
            )
            merge_entries(entries, {entry.key: entry})
        return entries
    for row in runner.run():
        value = _finite_or_none(row["value"])
        if value is None:
            continue
        entry = Entry(
            labels=tuple(str(row["labels"][label.key]) for label in labels),
            fingerprints=set(row["series_fingerprints"]),
            points={_hour_of(row["time"]): value},
        )
        merge_entries(entries, {entry.key: entry})
    return entries


@frozen
class QueriedHours:
    """The hourly buckets a fill query read, and the `[start, end)` range they cover."""

    entries: dict[EntryKey, Entry]
    start: dt.datetime
    end: dt.datetime


def query_hours(
    team: Team,
    precomputed_metric: MetricPrecomputedMetric,
    start: dt.datetime,
    end: dt.datetime,
    *,
    newest_first: bool = False,
    deadline: float = math.inf,
) -> QueriedHours:
    """The hourly buckets of `[start, end)` and the range they cover, splitting the range while the runner
    reports too many rows.

    Splits query the half next to the stored hours first: the older half for a forward fill, the newer half
    for a backfill (`newest_first`). After `deadline` (a `time.monotonic()` value) no further split query
    runs, so the returned range can be shorter than requested. It always touches the stored hours, so the
    caller can save it and extend its coverage.
    """
    try:
        return QueriedHours(entries=_query_hours(team, precomputed_metric, start, end), start=start, end=end)
    except MetricQueryTooManyRowsError:
        if end - start <= HOUR:
            raise TooManySeriesError("one hour has too many label sets; keep fewer labels")
    middle = start + (end - start) // 2 // HOUR * HOUR
    first, second = ((middle, end), (start, middle)) if newest_first else ((start, middle), (middle, end))
    queried = query_hours(team, precomputed_metric, *first, newest_first=newest_first, deadline=deadline)
    if (queried.start, queried.end) != first or time.monotonic() >= deadline:
        return queried
    more = query_hours(team, precomputed_metric, *second, newest_first=newest_first, deadline=deadline)
    merge_entries(queried.entries, more.entries)
    return QueriedHours(entries=queried.entries, start=min(queried.start, more.start), end=max(queried.end, more.end))


def _values(entries: dict[EntryKey, Entry], start: dt.datetime, end: dt.datetime) -> dict[tuple, Any]:
    return {
        (key, time): value
        for key, entry in entries.items()
        for time, value in entry.points.items()
        if start <= time < end
    }


def _changed(before: Any, after: Any) -> bool:
    if isinstance(before, list) or isinstance(after, list):
        return (
            not isinstance(before, list)
            or not isinstance(after, list)
            or len(before) != len(after)
            or any(_changed(a, b) for a, b in zip(before, after))
        )
    return abs(before - after) > _RELATIVE_TOLERANCE * max(abs(before), abs(after), 1.0)


def _any_changed(before: dict[tuple, Any], after: dict[tuple, Any]) -> bool:
    return before.keys() != after.keys() or any(_changed(before[key], after[key]) for key in before)


def fill_step(
    team: Team, precomputed_metric: MetricPrecomputedMetric, now: dt.datetime, *, deadline: float = math.inf
) -> bool:
    """Run the one fill that is due, forward before back. Returns False when nothing was due."""
    target = _floor_hour(now - dt.timedelta(seconds=precomputed_metric.settle_seconds))
    retention_start = _floor_hour(now - RETENTION)
    covered_from, covered_to = precomputed_metric.covered_from, precomputed_metric.covered_to
    if covered_from is None or covered_to is None:
        precomputed_metric.covered_from = precomputed_metric.covered_to = target
        precomputed_metric.save(update_fields=["covered_from", "covered_to", "updated_at"])
        return True
    if target > covered_to:
        start = max(covered_to - REREAD, covered_from)
        # The runner coarsens an hourly interval past 500 buckets, which would store multi-hour sums as hours.
        end = min(target, covered_to + MAX_FORWARD_STEP)
        queried = query_hours(team, precomputed_metric, start, end, deadline=deadline)
        entries, reached = queried.entries, queried.end
        reread_end = min(covered_to, reached)
        stored = _values(read_entries(precomputed_metric, start, reread_end), start, reread_end)
        if _any_changed(stored, _values(entries, start, reread_end)):
            precomputed_metric.settle_seconds = min(int(precomputed_metric.settle_seconds * 1.5), MAX_SETTLE_SECONDS)
        write_entries(precomputed_metric, start, reached, entries)
        precomputed_metric.covered_to = max(covered_to, reached)
        precomputed_metric.save(update_fields=["covered_to", "settle_seconds", "updated_at"])
        return True
    if covered_from > retention_start:
        start = max(covered_from - BACKFILL_STEP, retention_start)
        queried = query_hours(team, precomputed_metric, start, covered_from, newest_first=True, deadline=deadline)
        entries, reached = queried.entries, queried.start
        write_entries(precomputed_metric, reached, covered_from, entries)
        precomputed_metric.covered_from = reached
        precomputed_metric.save(update_fields=["covered_from", "updated_at"])
        return True
    return False


def _sweep(team_id: int, now: dt.datetime) -> None:
    metrics = MetricPrecomputedMetric.objects.for_team(team_id)
    metrics.filter(last_used_at__lt=now - UNUSED_AFTER).delete()
    first_kept_day = (now - RETENTION).astimezone(dt.UTC).date()
    MetricPrecomputedChunk.objects.for_team(team_id).filter(day__lt=first_kept_day).delete()
    metrics.filter(covered_from__lt=dt.datetime.combine(first_kept_day, dt.time(), tzinfo=dt.UTC)).update(
        covered_from=dt.datetime.combine(first_kept_day, dt.time(), tzinfo=dt.UTC)
    )


def _record_failure(precomputed_metric: MetricPrecomputedMetric, error: Exception, *, pause: bool) -> None:
    precomputed_metric.consecutive_failures += 1
    precomputed_metric.last_error = str(error)[:1000]
    if pause or precomputed_metric.consecutive_failures >= PAUSE_AFTER_FAILURES:
        precomputed_metric.state = MetricPrecomputedMetric.State.PAUSED
    precomputed_metric.save(update_fields=["consecutive_failures", "last_error", "state", "updated_at"])


def fill_precomputed_metrics(
    team_id: int, *, now: dt.datetime | None = None, budget: dt.timedelta = PASS_BUDGET
) -> None:
    """One pass over a team's precomputed metrics. Passes of one team never overlap, so it runs one fill at a time."""
    lock_key = f"metrics-precompute-fill:{team_id}"
    if not cache.add(lock_key, 1, timeout=_LOCK_TIMEOUT_SECONDS):
        return
    try:
        team = Team.objects.get(pk=team_id)
        now = now or dt.datetime.now(dt.UTC)
        _sweep(team_id, now)
        deadline = time.monotonic() + budget.total_seconds()
        pending = list(
            MetricPrecomputedMetric.objects.for_team(team_id)
            .filter(state=MetricPrecomputedMetric.State.ACTIVE)
            .order_by("created_at")
        )
        if not whole_hour_offset(team, now):
            return
        while pending and time.monotonic() < deadline:
            for precomputed_metric in list(pending):
                try:
                    did_work = fill_step(team, precomputed_metric, now, deadline=deadline)
                except TooManySeriesError as error:
                    _record_failure(precomputed_metric, error, pause=True)
                    did_work = False
                except Exception as error:
                    logger.exception("metrics_precompute_fill_failed", precomputed_metric_id=str(precomputed_metric.pk))
                    _record_failure(precomputed_metric, error, pause=False)
                    did_work = False
                else:
                    if did_work and precomputed_metric.consecutive_failures:
                        precomputed_metric.consecutive_failures = 0
                        precomputed_metric.save(update_fields=["consecutive_failures", "updated_at"])
                if not did_work:
                    pending.remove(precomputed_metric)
                if time.monotonic() >= deadline:
                    break
    finally:
        cache.delete(lock_key)


def teams_with_precomputed_metrics() -> list[int]:
    """Teams with any precomputed metric. Paused metrics count, because only a pass sweeps them away."""
    return list(MetricPrecomputedMetric.objects.unscoped().values_list("team_id", flat=True).distinct())
