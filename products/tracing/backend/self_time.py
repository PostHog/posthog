"""Per-span self-time annotation for full-trace payloads.

Self-time is the part of a span's duration not covered by its children — computed as an
interval union so overlapping or parallel children are only subtracted once. For a leaf
it equals the span's own duration; for a parent it is the unaccounted gap ("where did
the wall-clock actually go"), which is invisible from duration_nano alone.
"""

import datetime as dt
from collections import defaultdict

_MICROSECOND = dt.timedelta(microseconds=1)


def _as_datetime(value: dt.datetime | str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _bounds(span: dict) -> tuple[dt.datetime, dt.datetime]:
    """Return the span's start and end as datetimes.

    A cache-derived response carries them as ISO strings, because cache entries are JSON.
    """
    return _as_datetime(span["timestamp"]), _as_datetime(span["end_time"])


def annotate_self_time(spans: list[dict]) -> None:
    """Set `self_time_nano` on every span dict, in place.

    Expects the full span set of a trace (children grouped by `parent_span_id`).
    On a truncated trace the values overstate self-time for spans whose children were cut.
    """
    children_by_parent: dict[str, list[tuple[dt.datetime, dt.datetime]]] = defaultdict(list)
    for span in spans:
        children_by_parent[span["parent_span_id"]].append(_bounds(span))

    for span in spans:
        start, end = _bounds(span)
        intervals = sorted(
            (max(child_start, start), min(child_end, end))
            for child_start, child_end in children_by_parent.get(span["span_id"], [])
            if child_start < end and child_end > start
        )

        covered_ns = 0
        cursor = start
        for child_start, child_end in intervals:
            child_start = max(child_start, cursor)
            if child_end > child_start:
                covered_ns += ((child_end - child_start) // _MICROSECOND) * 1000
                cursor = child_end

        span["self_time_nano"] = max(span["duration_nano"] - covered_ns, 0)
