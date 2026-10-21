import json
from collections.abc import Callable, Sequence

from posthog.dataclasses import frozen

TAIL_TURN_SLACK_FACTOR = 4

STATE_METHODS = frozenset({"_posthog/run_started", "_posthog/sdk_session", "session/new"})
STATE_SESSION_UPDATES = frozenset({"current_mode_update", "available_commands_update"})
USAGE_METHOD = "_posthog/usage_update"
USAGE_SESSION_UPDATE = "usage_update"
PERMISSION_REQUEST = "_posthog/permission_request"
PERMISSION_RESOLVED = "_posthog/permission_resolved"
TURN_COMPLETE = "_posthog/turn_complete"
USER_SESSION_UPDATES = frozenset({"user_message_chunk", "user_message"})
STATE_MARKERS = (
    *STATE_METHODS,
    *STATE_SESSION_UPDATES,
    USAGE_SESSION_UPDATE,
    PERMISSION_REQUEST,
    PERMISSION_RESOLVED,
    TURN_COMPLETE,
    "user_message",
)


@frozen
class LogSlice:
    content: str
    offset: int
    count: int
    preamble: int = 0
    turns_before: int = 0


@frozen
class LogPartSummary:
    """What one log part contributes to a preamble, so a slice never reads a part that lies before it.

    ``state`` maps each state key to the last entry in the part that set it, as its index in the part and its
    line; ``requests`` holds the part's permission requests the same way, with their ids; ``resolved`` holds
    the request ids the part resolves. ``last_turn_complete`` is the index of its last turn completion, which
    closes every request before it, and ``user_turns`` counts the user turns that start in it.
    """

    count: int
    state: dict[str, tuple[int, str]]
    requests: list[tuple[int, str, str]]
    resolved: frozenset[str]
    last_turn_complete: int | None = None
    user_turns: int = 0


@frozen
class LogPart:
    """One storage object of a resume-chain log: its entries, and a summary that may come from a cache."""

    entries: Callable[[], list[str]]
    summary: Callable[[], LogPartSummary]


def log_entries(content: str) -> list[str]:
    return [line for line in content.split("\n") if line.strip().startswith("{")]


def _entry(line: str) -> dict:
    try:
        entry = json.loads(line)
    except ValueError:
        return {}
    return entry if isinstance(entry, dict) else {}


def _notification(line: str) -> dict:
    notification = _entry(line).get("notification")
    return notification if isinstance(notification, dict) else {}


def _session_update(notification: dict) -> dict:
    params = notification.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    return update if isinstance(update, dict) else {}


def _session_update_type(notification: dict) -> str | None:
    session_update = _session_update(notification).get("sessionUpdate")
    return session_update if isinstance(session_update, str) else None


def _is_user_message(line: str) -> bool:
    """A user turn in any log format the chat reads: the ACP chunk or whole-message update, the PostHog
    notification, or a legacy Pi event."""
    if "user_message" not in line:
        return False
    entry = _entry(line)
    event = entry.get("event")
    if entry.get("type") == "pi_event" and isinstance(event, dict):
        return event.get("type") == "user_message"
    notification = entry.get("notification")
    if not isinstance(notification, dict):
        return False
    if notification.get("method") == "_posthog/user_message":
        return True
    return notification.get("method") == "session/update" and _session_update_type(notification) in USER_SESSION_UPDATES


def _is_tool_call_start(line: str) -> bool:
    """A top-level tool call. A subagent's nested call renders under its parent card, so a slice that
    started at one would show nothing until the parent loads."""
    if '"tool_call"' not in line:
        return False
    notification = _notification(line)
    if notification.get("method") != "session/update" or _session_update_type(notification) != "tool_call":
        return False
    meta = _session_update(notification).get("_meta")
    claude_code = meta.get("claudeCode") if isinstance(meta, dict) else None
    return not (isinstance(claude_code, dict) and claude_code.get("parentToolCallId"))


def _request_id(notification: dict) -> str | None:
    params = notification.get("params")
    request_id = params.get("requestId") if isinstance(params, dict) else None
    return request_id if isinstance(request_id, str) else None


def _state_keys(notification: dict) -> list[str]:
    """The state keys an entry sets. Usage folds field by field, so each usage field is its own key."""
    method = notification.get("method")
    if method in STATE_METHODS:
        return [str(method)]
    if method == USAGE_METHOD:
        params = notification.get("params")
        return [f"usage:{field}" for field in params] if isinstance(params, dict) else []
    update_type = _session_update_type(notification)
    if method == "session/update" and update_type in STATE_SESSION_UPDATES:
        return [f"session/update:{update_type}"]
    if method == "session/update" and update_type == USAGE_SESSION_UPDATE:
        return [f"session-usage:{field}" for field in _session_update(notification) if field != "sessionUpdate"]
    return []


def summarize_log_part(entries: Sequence[str]) -> LogPartSummary:
    state: dict[str, tuple[int, str]] = {}
    requests: list[tuple[int, str, str]] = []
    resolved: set[str] = set()
    last_turn_complete: int | None = None
    user_turns = 0
    for index, line in enumerate(entries):
        if not any(marker in line for marker in STATE_MARKERS):
            continue
        if _is_user_message(line) and (index == 0 or not _is_user_message(entries[index - 1])):
            user_turns += 1
        notification = _notification(line)
        method = notification.get("method")
        if method == PERMISSION_REQUEST and (request_id := _request_id(notification)) is not None:
            requests.append((index, request_id, line))
        elif method == PERMISSION_RESOLVED and (request_id := _request_id(notification)) is not None:
            resolved.add(request_id)
        elif method == TURN_COMPLETE:
            last_turn_complete = index
        for key in _state_keys(notification):
            state[key] = (index, line)
    return LogPartSummary(
        count=len(entries),
        state=state,
        requests=requests,
        resolved=frozenset(resolved),
        last_turn_complete=last_turn_complete,
        user_turns=user_turns,
    )


def slice_log_parts_tail(parts: Sequence[LogPart], tail_bytes: int, before: int | None = None) -> LogSlice:
    """The latest entries of a multi-part JSONL log, cut where a user turn starts.

    The slice is the shortest suffix that starts at a user turn and holds at least ``tail_bytes``. A turn
    that alone grows past ``TAIL_TURN_SLACK_FACTOR`` times the budget is cut before one of its tool calls
    instead, so one long turn cannot bring back the full download. ``before`` ends the window at that
    entry index, so a client can page back through older turns. ``offset`` is the index of the first
    returned entry in the full log, the same index that ``log-N`` stream cursors use. The slice starts with
    ``preamble`` entries from before the cut that still set run state there. Only the parts that overlap
    the window are read; the parts before it contribute through their summaries.
    """
    summaries = [part.summary() for part in parts]
    starts: list[int] = []
    total = 0
    for summary in summaries:
        starts.append(total)
        total += summary.count
    end = total if before is None else min(max(before, 0), total)
    cap = tail_bytes * TAIL_TURN_SLACK_FACTOR
    loaded: dict[int, list[str]] = {}
    size = 0
    tool_cut: int | None = None
    cut = 0
    for part_index in range(len(parts) - 1, -1, -1):
        start = starts[part_index]
        if start >= end:
            continue
        entries = loaded[part_index] = parts[part_index].entries()
        found = False
        for local in range(min(len(entries), end - start) - 1, -1, -1):
            line = entries[local]
            size += len(line) + 1
            if size < tail_bytes:
                continue
            if _is_user_message(line) and (local == 0 or not _is_user_message(entries[local - 1])):
                cut, found = start + local, True
                break
            if tool_cut is None and _is_tool_call_start(line):
                tool_cut = start + local
            if size > cap and tool_cut is not None:
                cut, found = tool_cut, True
                break
        if found:
            break

    window: list[str] = []
    for part_index in sorted(loaded):
        start = starts[part_index]
        window += loaded[part_index][max(cut - start, 0) : max(min(end - start, len(loaded[part_index])), 0)]
    preamble = _preamble(summaries, starts, loaded, cut) if cut else []
    return LogSlice(
        content=_join([*preamble, *window]),
        offset=cut,
        count=total,
        preamble=len(preamble),
        turns_before=_turns_before(summaries, starts, loaded, cut),
    )


def _turns_before(
    summaries: Sequence[LogPartSummary], starts: Sequence[int], loaded: dict[int, list[str]], cut: int
) -> int:
    turns = 0
    for part_index, summary in enumerate(summaries):
        start = starts[part_index]
        if start >= cut:
            break
        if start + summary.count > cut:
            summary = summarize_log_part(loaded[part_index][: cut - start])
        turns += summary.user_turns
    return turns


def _preamble(
    summaries: Sequence[LogPartSummary], starts: Sequence[int], loaded: dict[int, list[str]], cut: int
) -> list[str]:
    """The entries before ``cut`` that still set run state there: the latest entry for each state key (run
    start, SDK session, starting mode, mode, commands, each usage field) and the permission requests nobody
    resolved."""
    resolved = frozenset().union(*(summary.resolved for summary in summaries))
    # A turn completion closes every request before it, resolved or not.
    closed_before = max(
        (
            starts[part_index] + summary.last_turn_complete
            for part_index, summary in enumerate(summaries)
            if summary.last_turn_complete is not None
        ),
        default=-1,
    )
    latest: dict[str, tuple[int, str]] = {}
    requests: list[tuple[int, str]] = []
    for part_index, summary in enumerate(summaries):
        start = starts[part_index]
        if start >= cut:
            break
        part = summarize_log_part(loaded[part_index][: cut - start]) if start + summary.count > cut else summary
        for key, (index, line) in part.state.items():
            latest[key] = (start + index, line)
        requests += [
            (start + index, line)
            for index, request_id, line in part.requests
            if request_id not in resolved and start + index > closed_before
        ]
    return [line for _, line in sorted({*latest.values(), *requests})]


def _join(entries: Sequence[str]) -> str:
    return "".join(f"{entry}\n" for entry in entries)


def slice_log_tail(content: str, tail_bytes: int, before: int | None = None) -> LogSlice:
    """``slice_log_parts_tail`` over a log held in one string."""
    entries = log_entries(content)
    part = LogPart(entries=lambda: entries, summary=lambda: summarize_log_part(entries))
    return slice_log_parts_tail([part], tail_bytes, before)
