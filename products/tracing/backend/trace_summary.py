"""Compact digest of one trace, for callers that cannot read every span (agents over MCP).

A full trace payload is a few hundred bytes per span, so a trace of a hundred-odd spans already
runs to tens of KB. The digest answers the usual first questions in a few KB instead: how long
the trace took, where the wall-clock went (self time and the critical path), which operations
repeat (N+1 queries), and which spans failed and why.
"""

from collections import defaultdict
from typing import Any

from posthog.dataclasses import frozen

NANOS_PER_MS = 1_000_000
STATUS_ERROR = 2

DEFAULT_SUMMARY_LIMIT = 10
MAX_SUMMARY_LIMIT = 50
MAX_CRITICAL_PATH_ENTRIES = 20
MIN_CRITICAL_PATH_SHARE = 0.01  # path entries below this share of the root's duration are dropped
MAX_CRITICAL_PATH_DEPTH = 100  # bounds the recursion on pathologically deep traces
MAX_SERVICES = 10
MAX_NAME_CHARS = 120
MAX_MESSAGE_CHARS = 200

# Where instrumentation puts the reason a span failed. OTel's status message is not stored, so
# the summary reads the exception event first, then the attributes instrumentations commonly set.
_EVENT_MESSAGE_KEYS = ("exception.message", "exception.type")
_ATTRIBUTE_MESSAGE_KEYS = (
    "exception.message",
    "error.message",
    "otel.status_description",
    "exception.type",
    "error.type",
    "http.response.status_code",
    "http.status_code",
)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _ms(nanos: float) -> float:
    return round(nanos / NANOS_PER_MS, 1)


def _span_ref(span: dict, *, root_service: str | None = None, with_id: bool = True) -> dict[str, Any]:
    ref: dict[str, Any] = {"span_id": span["span_id"]} if with_id else {}
    ref["name"] = _truncate(span["name"], MAX_NAME_CHARS)
    # Most spans share the root's service; naming it once in `root` saves bytes on every entry.
    if span["service_name"] != root_service:
        ref["service"] = _truncate(span["service_name"], MAX_NAME_CHARS)
    ref["duration_ms"] = _ms(span["duration_nano"])
    ref["self_ms"] = _ms(span.get("self_time_nano", span["duration_nano"]))
    if span["status_code"] == STATUS_ERROR:
        ref["error"] = True
    return ref


def _error_message(span: dict) -> str | None:
    for event in span.get("events") or []:
        attributes = event.get("attributes") or {}
        for key in _EVENT_MESSAGE_KEYS:
            if attributes.get(key):
                return _truncate(str(attributes[key]), MAX_MESSAGE_CHARS)
    attributes = span.get("attributes") or {}
    for key in _ATTRIBUTE_MESSAGE_KEYS:
        if attributes.get(key):
            message = f"{key}={attributes[key]}" if key.startswith("http.") else str(attributes[key])
            return _truncate(message, MAX_MESSAGE_CHARS)
    return None


def _critical_spans(root: dict, children_by_parent: dict[str, list[dict]]) -> list[tuple[int, dict]]:
    """The spans the trace's end time waits on, as (depth, span) in start order.

    Walks back from each span's end: the child that finished last is on the path, then the cursor
    moves to that child's start and the next child to finish before it is on the path too, and so
    on. A child that started at or after the cursor ran in parallel with one already on the path
    and finished earlier, so it is skipped. Each picked child is walked the same way. This is the
    critical path as tracing UIs draw it.
    """
    path: list[tuple[int, dict]] = []
    seen: set[str] = set()

    def walk(span: dict, depth: int) -> None:
        seen.add(span["span_id"])
        path.append((depth, span))
        if depth >= MAX_CRITICAL_PATH_DEPTH:
            return
        picked: list[dict] = []
        cursor = span["end_time"]
        for child in sorted(children_by_parent.get(span["span_id"], []), key=lambda c: c["end_time"], reverse=True):
            if child["span_id"] in seen or child["timestamp"] >= cursor:
                continue
            # The first pick may end past its parent (clock skew); later ones must end by the cursor.
            if picked and child["end_time"] > cursor:
                continue
            picked.append(child)
            cursor = child["timestamp"]
        for child in reversed(picked):
            walk(child, depth + 1)

    walk(root, 0)
    return path


@frozen
class _CriticalPath:
    entries: list[dict]
    omitted: int
    truncated: bool


def _critical_path(root: dict, children_by_parent: dict[str, list[dict]], max_entries: int) -> _CriticalPath:
    """The critical path, with runs of same-named siblings (N+1 loops) collapsed into one entry.

    Entries shorter than 1% of the root are dropped (their spans counted): a slow request's path is
    otherwise mostly sub-millisecond auth and cache calls that crowd out the span that matters.
    """
    # Collapsed runs sum in nanoseconds: rounding each span first turns a long run of sub-0.05ms
    # spans into zero and drops it below the threshold.
    runs: list[tuple[dict, int, int, int]] = []  # (entry, span count, duration nanos, self nanos)
    previous_key: tuple | None = None
    for depth, span in _critical_spans(root, children_by_parent):
        key = (depth, span["service_name"], span["name"])
        duration = span["duration_nano"]
        self_time = span.get("self_time_nano", duration)
        if key == previous_key:
            entry, count, total, total_self = runs[-1]
            if span["status_code"] == STATUS_ERROR:
                entry["error"] = True
            runs[-1] = (entry, count + 1, total + duration, total_self + self_time)
            continue
        previous_key = key
        entry = {"depth": depth, **_span_ref(span, root_service=root["service_name"], with_id=False)}
        runs.append((entry, 1, duration, self_time))
    min_nanos = root["duration_nano"] * MIN_CRITICAL_PATH_SHARE
    kept: list[dict] = []
    omitted = 0
    for entry, count, total, total_self in runs:
        if entry["depth"] != 0 and total < min_nanos:
            omitted += count
            continue
        if count > 1:
            entry["count"] = count
            entry["duration_ms"] = _ms(total)
            entry["self_ms"] = _ms(total_self)
        kept.append(entry)
    return _CriticalPath(entries=kept[:max_entries], omitted=omitted, truncated=len(kept) > max_entries)


def summarize_trace(spans: list[dict], *, limit: int = DEFAULT_SUMMARY_LIMIT, truncated: bool = False) -> dict:
    """Digest a trace's spans into a compact summary.

    Expects span dicts as the trace action builds them, with `self_time_nano` already annotated
    and `timestamp` / `end_time` as datetimes. `truncated` flags that `spans` is only the first
    page of a larger trace, so the counts are lower bounds.
    """
    if not spans:
        return {"span_count": 0, "truncated": truncated}

    span_ids = {span["span_id"] for span in spans}
    children_by_parent: dict[str, list[dict]] = defaultdict(list)
    roots: list[dict] = []
    for span in spans:
        if span["is_root_span"] or span["parent_span_id"] not in span_ids:
            roots.append(span)
        else:
            children_by_parent[span["parent_span_id"]].append(span)
    # A trace normally has one root. Several mean the real root has not arrived (or was cut by
    # paging); the longest of the orphans is the best stand-in for the request. None means the
    # parent links form a cycle (ingestion does not validate them), so any span has to stand in.
    root = max(roots or spans, key=lambda s: (s["is_root_span"], s["duration_nano"]))

    trace_start = min(span["timestamp"] for span in spans)
    trace_end = max(span["end_time"] for span in spans)

    services: dict[str, int] = defaultdict(int)
    for span in spans:
        services[span["service_name"]] += 1
    # Service names are not length-limited at ingestion, so every place they appear is bounded.
    top_services = {
        _truncate(service, MAX_NAME_CHARS): count
        for service, count in sorted(services.items(), key=lambda item: -item[1])[:MAX_SERVICES]
    }

    by_self_time = sorted(spans, key=lambda s: -s.get("self_time_nano", s["duration_nano"]))[:limit]

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for span in spans:
        groups[(span["service_name"], span["name"])].append(span)
    repeated: list[dict[str, Any]] = []
    for (service, name), members in groups.items():
        if len(members) < 2:
            continue
        group: dict[str, Any] = {"name": _truncate(name, MAX_NAME_CHARS)}
        if service != root["service_name"]:
            group["service"] = _truncate(service, MAX_NAME_CHARS)
        group["count"] = len(members)
        group["total_ms"] = _ms(sum(m["duration_nano"] for m in members))
        group["max_ms"] = _ms(max(m["duration_nano"] for m in members))
        repeated.append(group)
    repeated = sorted(repeated, key=lambda g: -g["total_ms"])[:limit]

    error_spans = [span for span in spans if span["status_code"] == STATUS_ERROR]
    errors = [
        {**_span_ref(span, root_service=root["service_name"]), "message": _error_message(span)}
        for span in sorted(error_spans, key=lambda s: s["timestamp"])[:limit]
    ]

    critical_path = _critical_path(root, children_by_parent, min(limit, MAX_CRITICAL_PATH_ENTRIES))
    root_service = root["service_name"]

    return {
        "trace_id": root["trace_id"],
        "start": trace_start.isoformat(),
        "duration_ms": _ms((trace_end - trace_start).total_seconds() * 1_000_000_000),
        "span_count": len(spans),
        "service_count": len(services),
        "error_count": len(error_spans),
        "truncated": truncated,
        "root": _span_ref(root),
        "services": top_services,
        "top_self_time": [_span_ref(span, root_service=root_service) for span in by_self_time],
        "critical_path": critical_path.entries,
        "critical_path_omitted": critical_path.omitted,
        "critical_path_truncated": critical_path.truncated,
        "repeated_spans": repeated,
        "errors": errors,
    }
