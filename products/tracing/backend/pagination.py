"""Trace list pagination: trim to N traces and build keyset cursors."""

import json
import base64
import datetime as dt
from typing import Any


def _parse_ts(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value
    if isinstance(value, str):
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unexpected timestamp type: {type(value)}")


def encode_trace_list_cursor(*, timestamp: dt.datetime, uuid: str) -> str:
    payload = json.dumps({"timestamp": timestamp.isoformat(), "uuid": uuid})
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def paginate_traces_in_results(
    results: list[dict[str, Any]],
    *,
    page_size: int,
    order_latest: bool,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    The runner may return spans for up to page_size + 1 traces. Keep the first
    `page_size` traces (by per-trace max/min timestamp) and build a keyset cursor.
    """
    if not results:
        return [], False, None

    by_trace: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        tid = row["trace_id"]
        by_trace.setdefault(tid, []).append(row)

    def trace_sort_ts(tid: str) -> dt.datetime:
        ts_list = [_parse_ts(r["timestamp"]) for r in by_trace[tid]]
        return max(ts_list) if order_latest else min(ts_list)

    sorted_tids = sorted(by_trace.keys(), key=trace_sort_ts, reverse=order_latest)
    has_more = len(sorted_tids) > page_size
    page_tids = sorted_tids[:page_size]
    page_tid_set = set(page_tids)

    trimmed = [r for r in results if r["trace_id"] in page_tid_set]

    next_cursor: str | None = None
    if has_more and page_tids:
        boundary_tid = page_tids[-1]
        boundary_spans = by_trace[boundary_tid]
        if order_latest:
            boundary_span = max(boundary_spans, key=lambda r: (_parse_ts(r["timestamp"]), r["uuid"]))
        else:
            boundary_span = min(boundary_spans, key=lambda r: (_parse_ts(r["timestamp"]), r["uuid"]))
        ts = _parse_ts(boundary_span["timestamp"])
        next_cursor = encode_trace_list_cursor(timestamp=ts, uuid=str(boundary_span["uuid"]))

    return trimmed, has_more, next_cursor
