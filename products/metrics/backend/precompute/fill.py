"""The fill loop: keeps each precomputed metric's hourly buckets stored, forward, back, and corrected.

Each pass over a team runs one query at a time through the ordinary metrics query runner, at an hourly
interval grouped by the kept labels. Forward fills store the hours that have settled since the last pass and
re-read the newest stored hours, so late samples replace what was stored and widen the settle delay. Once a
day, a re-fill re-reads the past day up to the forward re-read and rewrites the hours that late samples changed.
Capture drops samples more than 24 hours late, so a bucket written once that cap and an ingestion allowance have
passed is marked final and never read again. When nothing else is due, the pass backfills one day, newest first,
until the retention window is covered.
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
from products.metrics.backend.precompute.gate import precompute_enabled
from products.metrics.backend.precompute.store import (
    HOUR,
    MAX_ENTRIES_PER_CHUNK,
    MAX_FINGERPRINTS_PER_ENTRY,
    Entry,
    EntryKey,
    HourValue,
    TooManySeriesError,
    UnstorableLabelError,
    bucket_width,
    first_open_bucket,
    floor_to_bucket,
    merge_entries,
    read_entries,
    value_changed,
    write_entries,
)
from products.metrics.backend.promql import PromQLResponseTooLargeError, promql_range_results

logger = structlog.get_logger(__name__)

# Covers the longest range a query allows (31 days) plus the first bucket's alignment.
RETENTION = dt.timedelta(days=32)
BACKFILL_STEP = dt.timedelta(days=1)
MAX_FORWARD_STEP = dt.timedelta(days=1)
REREAD = dt.timedelta(hours=2)
# Capture rejects samples older than this.
LATENESS_CAP = dt.timedelta(hours=24)
MAX_SETTLE_SECONDS = 2 * 60 * 60
# A sample capture accepted just inside the lateness cap can still be on its way to ClickHouse, so a bucket turns
# final only once the longest settle delay has also passed.
FINAL_AFTER = LATENESS_CAP + dt.timedelta(seconds=MAX_SETTLE_SECONDS)
REFILL_EVERY = dt.timedelta(hours=24)
REFILL_WINDOW = dt.timedelta(hours=26)
# The re-fill reaches back to the oldest bucket that is not final yet, however old, so every bucket gets one
# re-read once it can no longer change. After a long gap in fills it catches up this much per step. A step holds
# every label set of its hours in memory until it writes them, so it stays as short as the forward and backfill
# steps. It must still cover `REFILL_WINDOW - REREAD`, so that a re-fill without a backlog completes in one step.
MAX_REFILL_STEP = dt.timedelta(days=1)
UNUSED_AFTER = dt.timedelta(days=14)
PAUSE_AFTER_FAILURES = 10
PASS_BUDGET = dt.timedelta(minutes=4)
# A larger Snuffle response splits the fill's range, as too many rows does, before it is decoded.
MAX_FILL_RESPONSE_BYTES = 50_000_000
_LOCK_TIMEOUT_SECONDS = 10 * 60


def _hour_of(value: Any) -> dt.datetime:
    return (dt.datetime.fromisoformat(value) if isinstance(value, str) else value).astimezone(dt.UTC)


def whole_hour_offset(team: Team, *moments: dt.datetime) -> bool:
    """Hourly UTC buckets tile the project's buckets only when its UTC offset is whole hours."""
    return all(
        (moment.astimezone(team.timezone_info).utcoffset() or dt.timedelta()) % HOUR == dt.timedelta()
        for moment in moments
    )


_PROMQL_FUNCTIONS = {
    PrecomputedMetricKind.SUM_OVER_TIME: "sum_over_time",
    PrecomputedMetricKind.BUCKET_INCREASE: "increase",
}


def query_promql_buckets(
    team: Team, precomputed_metric: MetricPrecomputedMetric, start: dt.datetime, end: dt.datetime
) -> dict[EntryKey, Entry]:
    """The buckets of `[start, end)` from Snuffle. Its point at `t` reads `(t - R, t]`, which is the bucket at `t - R`."""
    width = bucket_width(precomputed_metric)
    labels = [label.key for label in labels_of(precomputed_metric)]
    function = _PROMQL_FUNCTIONS[PrecomputedMetricKind(precomputed_metric.kind)]
    selector = f"{function}({precomputed_metric.metric_name}[{int(width.total_seconds())}s])"
    expr = f"sum by ({', '.join(labels)}) ({selector})" if labels else f"sum({selector})"
    try:
        results = promql_range_results(
            team, expr, start + width, end, width, record_query=False, max_bytes=MAX_FILL_RESPONSE_BYTES
        )
    except PromQLResponseTooLargeError as error:
        raise MetricQueryTooManyRowsError(str(error)) from error
    if len(results) > MAX_ENTRIES_PER_CHUNK:
        raise TooManySeriesError("one bucket has too many label sets; keep fewer labels")
    entries: dict[EntryKey, Entry] = {}
    for result in results:
        metric = result.get("metric") or {}
        points: dict[dt.datetime, HourValue] = {}
        for timestamp, raw in result.get("values") or []:
            value = _finite_or_none(float(raw))
            if value is not None:
                points[dt.datetime.fromtimestamp(float(timestamp), tz=dt.UTC) - width] = value
        entry = Entry(labels=tuple(str(metric.get(label, "")) for label in labels), points=points)
        merge_entries(entries, {entry.key: entry})
    return entries


def _query_hours(
    team: Team, precomputed_metric: MetricPrecomputedMetric, start: dt.datetime, end: dt.datetime
) -> dict[EntryKey, Entry]:
    if precomputed_metric.kind in _PROMQL_FUNCTIONS:
        return query_promql_buckets(team, precomputed_metric, start, end)
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
        # One more than the store keeps, so a row that hit the cap is known to be a sample.
        max_series_fingerprints=MAX_FINGERPRINTS_PER_ENTRY + 1,
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
        if end - start <= bucket_width(precomputed_metric):
            raise TooManySeriesError("one hour has too many label sets; keep fewer labels")
    width = bucket_width(precomputed_metric)
    middle = start + (end - start) // 2 // width * width
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


def _any_changed(before: dict[tuple, Any], after: dict[tuple, Any]) -> bool:
    return before.keys() != after.keys() or any(value_changed(before[key], after[key]) for key in before)


def _query_forward(
    team: Team,
    precomputed_metric: MetricPrecomputedMetric,
    start: dt.datetime,
    covered_to: dt.datetime,
    end: dt.datetime,
    deadline: float,
) -> QueriedHours:
    """The reread hours `[start, covered_to)` and the new hours `[covered_to, end)`, in one query when it fits.

    When the query must split, the new hours go first so that each pass moves `covered_to` forward. If the
    reread hours came first, a pass that ran out of time inside them would save no new hour, and every
    later pass would repeat the same work. The reread joins the result only when it finishes in time.
    """
    if start < covered_to:
        try:
            return QueriedHours(entries=_query_hours(team, precomputed_metric, start, end), start=start, end=end)
        except MetricQueryTooManyRowsError:
            pass
    fresh = query_hours(team, precomputed_metric, covered_to, end, deadline=deadline)
    if start >= covered_to or fresh.end < end or time.monotonic() >= deadline:
        return fresh
    reread = query_hours(team, precomputed_metric, start, covered_to, deadline=deadline)
    if reread.end < covered_to:
        return fresh
    merge_entries(reread.entries, fresh.entries)
    return QueriedHours(entries=reread.entries, start=start, end=end)


def fill_step(
    team: Team, precomputed_metric: MetricPrecomputedMetric, now: dt.datetime, *, deadline: float = math.inf
) -> bool:
    """Run the one fill that is due: forward, then the daily re-fill, then back. Returns False when nothing was due."""
    width = bucket_width(precomputed_metric)
    target = floor_to_bucket(now - dt.timedelta(seconds=precomputed_metric.settle_seconds), width)
    retention_start = floor_to_bucket(now - RETENTION, width)
    final_before = now - FINAL_AFTER
    covered_from, covered_to = precomputed_metric.covered_from, precomputed_metric.covered_to
    if covered_from is None or covered_to is None:
        precomputed_metric.covered_from = precomputed_metric.covered_to = target
        precomputed_metric.save(update_fields=["covered_from", "covered_to", "updated_at"])
        return True
    if target > covered_to:
        start = max(covered_to - max(REREAD, width), covered_from)
        # The runner coarsens an hourly interval past 500 buckets, which would store multi-hour sums as hours.
        end = min(target, covered_to + MAX_FORWARD_STEP)
        queried = _query_forward(team, precomputed_metric, start, covered_to, end, deadline)
        reread_end = min(covered_to, queried.end)
        stored = _values(read_entries(precomputed_metric, queried.start, reread_end), queried.start, reread_end)
        if _any_changed(stored, _values(queried.entries, queried.start, reread_end)):
            precomputed_metric.settle_seconds = min(int(precomputed_metric.settle_seconds * 1.5), MAX_SETTLE_SECONDS)
        write_entries(precomputed_metric, queried.start, queried.end, queried.entries, final_before=final_before)
        precomputed_metric.covered_to = max(covered_to, queried.end)
        precomputed_metric.save(update_fields=["covered_to", "settle_seconds", "updated_at"])
        return True
    refilled_at = precomputed_metric.refilled_at
    if refilled_at is None or refilled_at <= now - REFILL_EVERY:
        _refill(team, precomputed_metric, now, deadline)
        return True
    if covered_from > retention_start:
        start = max(covered_from - BACKFILL_STEP, retention_start)
        queried = query_hours(team, precomputed_metric, start, covered_from, newest_first=True, deadline=deadline)
        entries, reached = queried.entries, queried.start
        write_entries(precomputed_metric, reached, covered_from, entries, final_before=final_before)
        precomputed_metric.covered_from = reached
        precomputed_metric.save(update_fields=["covered_from", "updated_at"])
        return True
    return False


def _refill(team: Team, precomputed_metric: MetricPrecomputedMetric, now: dt.datetime, deadline: float) -> None:
    """Re-read the past day before the forward re-read, rewrite the buckets that changed, and mark the ones that can no
    longer change final. It starts earlier when an older bucket is not final yet."""
    width = bucket_width(precomputed_metric)
    covered_from, covered_to = precomputed_metric.covered_from, precomputed_metric.covered_to
    assert covered_from is not None and covered_to is not None
    start = floor_to_bucket(now - REFILL_WINDOW, width)
    oldest_open = first_open_bucket(precomputed_metric, covered_from)
    if oldest_open is not None:
        start = min(start, oldest_open)
    start = max(start, covered_from)
    end = min(floor_to_bucket(now - REREAD, width), covered_to)
    complete = True
    if start < end:
        # The runner coarsens an hourly interval past 500 buckets, which would store multi-hour sums as hours.
        queried = query_hours(team, precomputed_metric, start, min(end, start + MAX_REFILL_STEP), deadline=deadline)
        changed = write_entries(
            precomputed_metric, queried.start, queried.end, queried.entries, final_before=now - FINAL_AFTER
        )
        complete = queried.end >= end
        logger.info(
            "metrics_precompute_refilled",
            precomputed_metric_id=str(precomputed_metric.pk),
            buckets_written=changed,
            complete=complete,
        )
    if complete:
        precomputed_metric.refilled_at = now
        precomputed_metric.save(update_fields=["refilled_at", "updated_at"])


def _sweep(team_id: int, now: dt.datetime) -> None:
    metrics = MetricPrecomputedMetric.objects.for_team(team_id)
    metrics.filter(last_used_at__lt=now - UNUSED_AFTER).delete()
    first_kept = dt.datetime.combine((now - RETENTION).astimezone(dt.UTC).date(), dt.time(), tzinfo=dt.UTC)
    MetricPrecomputedChunk.objects.for_team(team_id).filter(start__lt=first_kept).delete()
    metrics.filter(covered_from__lt=first_kept).update(covered_from=first_kept)


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
        if not precompute_enabled(team):
            return
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
                except (TooManySeriesError, UnstorableLabelError) as error:
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
