"""Connect-time merge support for thin-tail task run streams.

A thin-tail run keeps only a short live tail in Redis and serves history from
the durable run log. The agent stamps a shared ``event_id`` on each event in
both stores (format ``<boot>-<seq>``: a random per-boot prefix and a counter
monotonic within that boot). A log entry coalesced from a run of chunk events
carries the covered range as ``first_event_id``..``event_id``.

``TaskRunStreamBacklogIndex`` collects the ids (and ranges) present in the log
backlog so the SSE view can drop live-tail entries the backlog already covers.
Entries without ids (older agents, server-published events) are never dropped.
"""

TASK_RUN_STREAM_LOG_CURSOR_PREFIX = "log-"


def _parse_event_id(event_id: str) -> tuple[str, int] | None:
    boot, _, seq = event_id.rpartition("-")
    if not boot:
        return None
    try:
        return boot, int(seq)
    except ValueError:
        return None


def parse_log_cursor(last_event_id: str) -> int | None:
    """Index of the last served backlog entry, or ``None`` for any other cursor.

    Accepts only what ``format_log_cursor`` emits: plain non-negative ASCII
    decimals. ``int()`` alone would also take signs, whitespace, underscores and
    non-ASCII digits, turning a caller-supplied header into a negative or
    out-of-range list index downstream.
    """
    if not last_event_id.startswith(TASK_RUN_STREAM_LOG_CURSOR_PREFIX):
        return None
    suffix = last_event_id[len(TASK_RUN_STREAM_LOG_CURSOR_PREFIX) :]
    if not suffix.isascii() or not suffix.isdigit():
        return None
    return int(suffix)


def format_log_cursor(index: int) -> str:
    return f"{TASK_RUN_STREAM_LOG_CURSOR_PREFIX}{index}"


class TaskRunStreamBacklogIndex:
    def __init__(self, entries: list[dict]) -> None:
        self._ids: set[str] = set()
        self._ranges: dict[str, list[tuple[int, int]]] = {}
        for entry in entries:
            event_id = entry.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                continue
            self._ids.add(event_id)
            first_event_id = entry.get("first_event_id")
            if not isinstance(first_event_id, str) or not first_event_id:
                continue
            first = _parse_event_id(first_event_id)
            last = _parse_event_id(event_id)
            if first is None or last is None or first[0] != last[0]:
                self._ids.add(first_event_id)
                continue
            self._ranges.setdefault(first[0], []).append((first[1], last[1]))

    def covers(self, event: dict) -> bool:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return False
        if event_id in self._ids:
            return True
        parsed = _parse_event_id(event_id)
        if parsed is None:
            return False
        return self._covers_parsed(*parsed)

    def has_gap_before(self, event: dict) -> bool:
        """True when the event's per-boot predecessor is missing from the log backlog.

        Meaningful only for the first id-carrying live entry the backlog does not
        cover: a hole before it means Redis evicted events whose log batch never
        landed, which is the one loss mode thin-tail trimming cannot rule out.
        """
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return False
        parsed = _parse_event_id(event_id)
        if parsed is None:
            return False
        boot, seq = parsed
        if seq <= 1:
            return False
        return not self._covers_parsed(boot, seq - 1)

    def _covers_parsed(self, boot: str, seq: int) -> bool:
        if f"{boot}-{seq}" in self._ids:
            return True
        return any(lo <= seq <= hi for lo, hi in self._ranges.get(boot, ()))
