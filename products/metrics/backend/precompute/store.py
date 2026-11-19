"""Read and write a precomputed metric's hourly buckets, kept in one Postgres row per UTC day.

A chunk holds one entry per kept label set (and, for a histogram, per bucket layout). An entry lists its hours
as `[hour of the day, value]`, where the value is a summed increase or a list of summed bucket counts. A write
replaces the hours it covers and leaves the others, so a repeated fill rewrites the same values.
"""

import math
import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field

from django.db import transaction

from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric

HOUR = dt.timedelta(hours=1)

EntryKey = tuple[tuple[str, ...], str, tuple[float, ...]]
HourValue = float | list[float]

# One chunk is one JSONB value that every pass decodes whole, so a day keeps at most this many label sets.
MAX_ENTRIES_PER_CHUNK = 10_000
# Fingerprints only resolve a series' unit, so a sample of them is enough. Without a cap, an entry with no
# kept labels collects every physical series of the day.
MAX_FINGERPRINTS_PER_ENTRY = 100


class TooManySeriesError(Exception):
    pass


@dataclass(frozen=False)
class Entry:
    """One kept label set's hours. `metric_type` and `bounds` tell histogram layouts apart and are empty otherwise."""

    labels: tuple[str, ...]
    metric_type: str = ""
    bounds: tuple[float, ...] = ()
    fingerprints: set[int] = field(default_factory=set)
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
        existing.points.update(entry.points)


def _days(start: dt.datetime, end: dt.datetime) -> Iterator[dt.date]:
    day = start.astimezone(dt.UTC).date()
    while dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC) < end:
        yield day
        day += dt.timedelta(days=1)


def _day_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)


def _decode(day: dt.date, series: list[dict]) -> dict[EntryKey, Entry]:
    entries: dict[EntryKey, Entry] = {}
    for item in series:
        entry = Entry(
            labels=tuple(item["labels"]),
            metric_type=item.get("metric_type", ""),
            bounds=tuple(float(bound) for bound in item.get("bounds", ())),
            fingerprints=set(item.get("fingerprints", ())),
            points={_day_start(day) + hour * HOUR: value for hour, value in item["points"]},
        )
        entries[entry.key] = entry
    return entries


def _encode(day: dt.date, entries: dict[EntryKey, Entry]) -> list[dict]:
    series = []
    for key in sorted(entries):
        entry = entries[key]
        if not entry.points:
            continue
        item: dict = {
            "labels": list(entry.labels),
            "fingerprints": sorted(entry.fingerprints)[:MAX_FINGERPRINTS_PER_ENTRY],
            "points": [[(time - _day_start(day)) // HOUR, entry.points[time]] for time in sorted(entry.points)],
        }
        if entry.metric_type or entry.bounds:
            item["metric_type"] = entry.metric_type
            # JSONB has no NaN or Infinity, so those bounds are stored as the strings `float()` reads back.
            item["bounds"] = [bound if math.isfinite(bound) else str(bound) for bound in entry.bounds]
        series.append(item)
    return series


def read_entries(
    precomputed_metric: MetricPrecomputedMetric, start: dt.datetime, end: dt.datetime
) -> dict[EntryKey, Entry]:
    """The stored hours in `[start, end)`, merged across days."""
    entries: dict[EntryKey, Entry] = {}
    chunks = MetricPrecomputedChunk.objects.for_team(precomputed_metric.team_id).filter(
        precomputed_metric=precomputed_metric, day__in=list(_days(start, end))
    )
    for chunk in chunks:
        day_entries = _decode(chunk.day, chunk.series)
        for entry in day_entries.values():
            entry.points = {time: value for time, value in entry.points.items() if start <= time < end}
        merge_entries(entries, {key: entry for key, entry in day_entries.items() if entry.points})
    return entries


def write_entries(
    precomputed_metric: MetricPrecomputedMetric,
    start: dt.datetime,
    end: dt.datetime,
    entries: dict[EntryKey, Entry],
) -> None:
    """Replace the stored hours in `[start, end)` with `entries`, one day at a time."""
    team_id = precomputed_metric.team_id
    for day in _days(start, end):
        day_from, day_to = max(start, _day_start(day)), min(end, _day_start(day + dt.timedelta(days=1)))
        with transaction.atomic():
            chunk = (
                MetricPrecomputedChunk.objects.for_team(team_id)
                .select_for_update()
                .filter(precomputed_metric=precomputed_metric, day=day)
                .first()
            )
            stored = _decode(day, chunk.series) if chunk is not None else {}
            for entry in stored.values():
                entry.points = {time: value for time, value in entry.points.items() if not day_from <= time < day_to}
            merge_entries(
                stored,
                {
                    key: Entry(
                        labels=entry.labels,
                        metric_type=entry.metric_type,
                        bounds=entry.bounds,
                        fingerprints=set(entry.fingerprints),
                        points={time: value for time, value in entry.points.items() if day_from <= time < day_to},
                    )
                    for key, entry in entries.items()
                },
            )
            series = _encode(day, stored)
            if len(series) > MAX_ENTRIES_PER_CHUNK:
                raise TooManySeriesError("one day has too many label sets; keep fewer labels")
            if chunk is None:
                if series:
                    MetricPrecomputedChunk.objects.for_team(team_id).create(
                        team_id=team_id, precomputed_metric=precomputed_metric, day=day, series=series
                    )
            else:
                chunk.series = series
                chunk.save(update_fields=["series", "computed_at"])
