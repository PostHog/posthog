"""Read and write a precomputed metric's buckets, kept in one Postgres row per bucket.

A chunk holds one entry per kept label set (and, for a histogram, per bucket layout), with the bucket's value:
a summed increase or sum, or a list of summed bucket counts. A write compares each bucket with what is stored
and rewrites only the buckets whose values changed, so a repeated fill writes nothing. A final bucket is past
capture's lateness cap and is never rewritten.
"""

import math
import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric

HOUR = dt.timedelta(hours=1)

EntryKey = tuple[tuple[str, ...], str, tuple[float, ...]]
HourValue = float | list[float]

# One chunk is one JSONB value that a read decodes whole, so a bucket keeps at most this many label sets.
MAX_ENTRIES_PER_CHUNK = 10_000
# Without a cap, an entry with no kept labels collects every physical series of the bucket.
MAX_FINGERPRINTS_PER_ENTRY = 100
_RELATIVE_TOLERANCE = 1e-9


class TooManySeriesError(Exception):
    pass


class UnstorableLabelError(Exception):
    """A kept label value holds a NUL character, which Postgres JSONB cannot store."""


class TooManyStoredPointsError(Exception):
    """The stored range holds more label-set buckets than one read may load."""


@dataclass(frozen=False)
class Entry:
    """One kept label set's buckets. `metric_type` and `bounds` tell histogram layouts apart and are empty otherwise."""

    labels: tuple[str, ...]
    metric_type: str = ""
    bounds: tuple[float, ...] = ()
    fingerprints: set[int] = field(default_factory=set)
    # Set when `fingerprints` is a sample. A dropped series can carry another unit, so the unit is unknown.
    fingerprints_truncated: bool = False
    points: dict[dt.datetime, HourValue] = field(default_factory=dict)

    @property
    def key(self) -> EntryKey:
        return (self.labels, self.metric_type, self.bounds)


def merge_entries(target: dict[EntryKey, Entry], source: dict[EntryKey, Entry]) -> None:
    for key, entry in source.items():
        existing = target.setdefault(
            key, Entry(labels=entry.labels, metric_type=entry.metric_type, bounds=entry.bounds)
        )
        existing.fingerprints |= entry.fingerprints
        existing.fingerprints_truncated |= entry.fingerprints_truncated
        existing.points.update(entry.points)


def bucket_width(precomputed_metric: MetricPrecomputedMetric) -> dt.timedelta:
    return dt.timedelta(seconds=precomputed_metric.bucket_seconds)


def floor_to_bucket(value: dt.datetime, width: dt.timedelta) -> dt.datetime:
    """The start of the UTC bucket that holds `value`. Buckets start on multiples of `width` since the epoch."""
    seconds = int(width.total_seconds())
    timestamp = int(value.timestamp())
    return dt.datetime.fromtimestamp(timestamp - timestamp % seconds, tz=dt.UTC)


def _bucket_starts(start: dt.datetime, end: dt.datetime, width: dt.timedelta) -> Iterator[dt.datetime]:
    bucket = floor_to_bucket(start, width)
    while bucket < end:
        yield bucket
        bucket += width


def value_changed(before: Any, after: Any) -> bool:
    if isinstance(before, list) or isinstance(after, list):
        return (
            not isinstance(before, list)
            or not isinstance(after, list)
            or len(before) != len(after)
            or any(value_changed(a, b) for a, b in zip(before, after))
        )
    return abs(before - after) > _RELATIVE_TOLERANCE * max(abs(before), abs(after), 1.0)


def _decode(start: dt.datetime, series: list[dict]) -> dict[EntryKey, Entry]:
    entries: dict[EntryKey, Entry] = {}
    for item in series:
        entry = Entry(
            labels=tuple(item["labels"]),
            metric_type=item.get("metric_type", ""),
            bounds=tuple(float(bound) for bound in item.get("bounds", ())),
            fingerprints=set(item.get("fingerprints", ())),
            fingerprints_truncated=item.get("fingerprints_truncated", False),
            points={start: item["value"]},
        )
        entries[entry.key] = entry
    return entries


def _encode(start: dt.datetime, entries: dict[EntryKey, Entry]) -> list[dict]:
    series = []
    for key in sorted(entries):
        entry = entries[key]
        if start not in entry.points:
            continue
        if any("\x00" in label for label in entry.labels):
            raise UnstorableLabelError("a kept label value contains a NUL character; keep fewer labels")
        item: dict = {
            "labels": list(entry.labels),
            "fingerprints": sorted(entry.fingerprints)[:MAX_FINGERPRINTS_PER_ENTRY],
            "value": entry.points[start],
        }
        if entry.fingerprints_truncated or len(entry.fingerprints) > MAX_FINGERPRINTS_PER_ENTRY:
            item["fingerprints_truncated"] = True
        if entry.metric_type or entry.bounds:
            item["metric_type"] = entry.metric_type
            # JSONB has no NaN or Infinity, so those bounds are stored as the strings `float()` reads back.
            item["bounds"] = [bound if math.isfinite(bound) else str(bound) for bound in entry.bounds]
        series.append(item)
    return series


def _series_changed(before: list[dict], after: list[dict]) -> bool:
    """Whether a bucket's stored series differ from new ones, by more than float noise in a value."""

    def keyed(series: list[dict]) -> dict[tuple, Any]:
        return {
            (tuple(item["labels"]), item.get("metric_type", ""), tuple(map(str, item.get("bounds", ())))): item
            for item in series
        }

    old, new = keyed(before), keyed(after)
    return old.keys() != new.keys() or any(
        value_changed(old[key]["value"], new[key]["value"])
        or old[key]["fingerprints"] != new[key]["fingerprints"]
        or old[key].get("fingerprints_truncated") != new[key].get("fingerprints_truncated")
        for key in old
    )


def read_entries(
    precomputed_metric: MetricPrecomputedMetric,
    start: dt.datetime,
    end: dt.datetime,
    max_points: int | None = None,
) -> dict[EntryKey, Entry]:
    """The stored buckets that start in `[start, end)`, merged. Raises `TooManyStoredPointsError` as soon as more
    than `max_points` label-set buckets are read, so the buckets after that are never decoded."""
    entries: dict[EntryKey, Entry] = {}
    points = 0
    chunks = (
        MetricPrecomputedChunk.objects.for_team(precomputed_metric.team_id)
        .filter(precomputed_metric=precomputed_metric, start__gte=start, start__lt=end)
        .order_by("start")
        .only("start", "series")
    )
    for chunk in chunks.iterator(chunk_size=500):
        bucket_entries = _decode(chunk.start, chunk.series)
        points += len(bucket_entries)
        if max_points is not None and points > max_points:
            raise TooManyStoredPointsError
        merge_entries(entries, bucket_entries)
    return entries


def first_open_bucket(precomputed_metric: MetricPrecomputedMetric, since: dt.datetime) -> dt.datetime | None:
    """The oldest stored bucket from `since` on that is not final yet."""
    return (
        MetricPrecomputedChunk.objects.for_team(precomputed_metric.team_id)
        .filter(precomputed_metric=precomputed_metric, final=False, start__gte=since)
        .order_by("start")
        .values_list("start", flat=True)
        .first()
    )


def write_entries(
    precomputed_metric: MetricPrecomputedMetric,
    start: dt.datetime,
    end: dt.datetime,
    entries: dict[EntryKey, Entry],
    *,
    final_before: dt.datetime | None = None,
) -> int:
    """Make the stored buckets in `[start, end)` hold `entries`, and return how many buckets were written.

    A bucket is written only when its values changed, or when it ends by `final_before` and turns final. A final
    bucket is never rewritten, and a bucket with no entries keeps no row.
    """
    team_id = precomputed_metric.team_id
    width = bucket_width(precomputed_metric)
    starts = list(_bucket_starts(start, end, width))
    created: list[MetricPrecomputedChunk] = []
    updated: list[MetricPrecomputedChunk] = []
    emptied: list[Any] = []
    with transaction.atomic():
        stored = {
            chunk.start: chunk
            for chunk in MetricPrecomputedChunk.objects.for_team(team_id)
            .select_for_update()
            .filter(precomputed_metric=precomputed_metric, start__gte=start, start__lt=end)
        }
        for bucket in starts:
            chunk = stored.get(bucket)
            if chunk is not None and chunk.final:
                continue
            series = _encode(bucket, entries)
            if len(series) > MAX_ENTRIES_PER_CHUNK:
                raise TooManySeriesError("one bucket has too many label sets; keep fewer labels")
            final = final_before is not None and bucket + width <= final_before
            if not series:
                if chunk is not None:
                    emptied.append(chunk.pk)
                continue
            if chunk is None:
                created.append(
                    MetricPrecomputedChunk(
                        team_id=team_id, precomputed_metric=precomputed_metric, start=bucket, series=series, final=final
                    )
                )
            elif _series_changed(chunk.series, series) or final != chunk.final:
                chunk.series, chunk.final = series, final
                updated.append(chunk)
        if emptied:
            MetricPrecomputedChunk.objects.for_team(team_id).filter(pk__in=emptied).delete()
        if created:
            MetricPrecomputedChunk.objects.for_team(team_id).bulk_create(created)
        if updated:
            # `bulk_update` skips `auto_now`, so the write time is set here.
            for chunk in updated:
                chunk.computed_at = dt.datetime.now(dt.UTC)
            MetricPrecomputedChunk.objects.for_team(team_id).bulk_update(updated, ["series", "final", "computed_at"])
    return len(created) + len(updated) + len(emptied)
