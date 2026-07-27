"""Per-span self-time annotation for full-trace payloads.

Self-time is the part of a span's duration not covered by its children — computed as an
interval union so overlapping or parallel children are only subtracted once. For a leaf
it equals the span's own duration; for a parent it is the unaccounted gap ("where did
the wall-clock actually go"), which is invisible from duration_nano alone.
"""

import datetime as dt
from collections import defaultdict

_MICROSECOND = dt.timedelta(microseconds=1)


def annotate_self_time(spans: list[dict]) -> None:
    """Set `self_time_nano` on every span dict, in place.

    Expects the full span set of a trace (children grouped by `parent_span_id`);
    `timestamp` / `end_time` must still be datetimes. On a truncated trace the values
    overstate self-time for spans whose children were cut.
    """
    children_by_parent: dict[str, list[dict]] = defaultdict(list)
    for span in spans:
        children_by_parent[span["parent_span_id"]].append(span)

    for span in spans:
        start, end = span["timestamp"], span["end_time"]
        intervals = sorted(
            (max(child["timestamp"], start), min(child["end_time"], end))
            for child in children_by_parent.get(span["span_id"], [])
            if child["timestamp"] < end and child["end_time"] > start
        )

        covered_ns = 0
        cursor = start
        for child_start, child_end in intervals:
            child_start = max(child_start, cursor)
            if child_end > child_start:
                covered_ns += ((child_end - child_start) // _MICROSECOND) * 1000
                cursor = child_end

        span["self_time_nano"] = max(span["duration_nano"] - covered_ns, 0)
