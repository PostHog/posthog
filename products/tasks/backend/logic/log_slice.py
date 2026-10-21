import json

from posthog.dataclasses import frozen

TAIL_TURN_SLACK_FACTOR = 4


PREAMBLE_METHODS = frozenset({"_posthog/run_started", "_posthog/sdk_session", "_posthog/usage_update"})
PREAMBLE_SESSION_UPDATES = frozenset({"usage_update", "current_mode_update", "available_commands_update"})
PERMISSION_REQUEST = "_posthog/permission_request"
PERMISSION_RESOLVED = "_posthog/permission_resolved"


@frozen
class LogSlice:
    content: str
    offset: int
    count: int
    preamble: int = 0


def _log_entries(content: str) -> list[str]:
    return [line for line in content.split("\n") if line.strip().startswith("{")]


def _notification(line: str) -> dict:
    try:
        entry = json.loads(line)
    except ValueError:
        return {}
    notification = entry.get("notification") if isinstance(entry, dict) else None
    return notification if isinstance(notification, dict) else {}


def _session_update_type(notification: dict) -> str | None:
    params = notification.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    session_update = update.get("sessionUpdate") if isinstance(update, dict) else None
    return session_update if isinstance(session_update, str) else None


def _is_user_message(line: str) -> bool:
    if "user_message" not in line:
        return False
    notification = _notification(line)
    if notification.get("method") == "_posthog/user_message":
        return True
    return notification.get("method") == "session/update" and _session_update_type(notification) == "user_message_chunk"


def _is_tool_call_start(line: str) -> bool:
    if '"tool_call"' not in line:
        return False
    notification = _notification(line)
    return notification.get("method") == "session/update" and _session_update_type(notification) == "tool_call"


def _request_id(notification: dict) -> str | None:
    params = notification.get("params")
    request_id = params.get("requestId") if isinstance(params, dict) else None
    return request_id if isinstance(request_id, str) else None


def _preamble(entries: list[str], cut: int) -> list[str]:
    """The entries before ``cut`` that still set run state there: the latest of each state frame
    (run start, SDK session, usage, mode, commands) and the permission requests nobody resolved."""
    resolved: set[str] = set()
    for line in entries:
        if PERMISSION_RESOLVED in line:
            notification = _notification(line)
            request_id = _request_id(notification)
            if notification.get("method") == PERMISSION_RESOLVED and request_id is not None:
                resolved.add(request_id)
    markers = (*PREAMBLE_METHODS, *PREAMBLE_SESSION_UPDATES, PERMISSION_REQUEST)
    latest: dict[str, int] = {}
    open_requests: list[int] = []
    for index in range(cut):
        line = entries[index]
        if not any(marker in line for marker in markers):
            continue
        notification = _notification(line)
        method = notification.get("method")
        update = _session_update_type(notification)
        if method in PREAMBLE_METHODS:
            latest[str(method)] = index
        elif method == "session/update" and update in PREAMBLE_SESSION_UPDATES:
            latest[f"session/update:{update}"] = index
        elif method == PERMISSION_REQUEST and _request_id(notification) not in resolved:
            open_requests.append(index)
    return [entries[index] for index in sorted({*latest.values(), *open_requests})]


def _join(entries: list[str]) -> str:
    return "".join(f"{entry}\n" for entry in entries)


def slice_log_tail(content: str, tail_bytes: int, before: int | None = None) -> LogSlice:
    """The latest entries of a JSONL log, cut where a user turn starts.

    The slice is the shortest suffix that starts at a user turn and holds at least
    ``tail_bytes``. A turn that alone grows past ``TAIL_TURN_SLACK_FACTOR`` times the
    budget is cut before one of its tool calls instead, so one long turn cannot
    bring back the full download. ``offset`` is the index of the first returned
    entry in the full log, the same index that ``log-N`` stream cursors use. The slice
    starts with ``preamble`` entries from before the cut that still set run state there.
    ``before`` ends the window at that index, so a client can page back through older turns.
    """
    all_entries = _log_entries(content)
    end = len(all_entries) if before is None else min(max(before, 0), len(all_entries))
    entries = all_entries[:end]
    cap = tail_bytes * TAIL_TURN_SLACK_FACTOR
    size = 0
    tool_cut: int | None = None
    cut = 0
    for index in range(len(entries) - 1, -1, -1):
        size += len(entries[index]) + 1
        if size < tail_bytes:
            continue
        line = entries[index]
        if _is_user_message(line) and (index == 0 or not _is_user_message(entries[index - 1])):
            cut = index
            break
        if tool_cut is None and _is_tool_call_start(line):
            tool_cut = index
        if size > cap and tool_cut is not None:
            cut = tool_cut
            break
    preamble = _preamble(entries, cut) if cut else []
    return LogSlice(
        content=_join([*preamble, *entries[cut:]]), offset=cut, count=len(all_entries), preamble=len(preamble)
    )
