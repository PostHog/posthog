import json
import bisect
import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence

from posthog.dataclasses import frozen

from products.posthog_ai.backend.turn_suggestions.transcript import HumanTurnCounter, human_text, is_turn_text

TAIL_TURN_SLACK_FACTOR = 4
START_READ_MAX_BYTES = 8 * 1024 * 1024

STATE_METHODS = frozenset({"_posthog/run_started", "_posthog/sdk_session", "session/new"})
STATE_SESSION_UPDATES = frozenset({"current_mode_update", "available_commands_update"})
USAGE_METHOD = "_posthog/usage_update"
USAGE_SESSION_UPDATE = "usage_update"
PERMISSION_REQUEST = "_posthog/permission_request"
PERMISSION_RESOLVED = "_posthog/permission_resolved"
TURN_COMPLETE = "_posthog/turn_complete"
USER_MESSAGE_METHOD = "_posthog/user_message"
PROMPT_METHOD = "session/prompt"
USER_SESSION_UPDATES = frozenset({"user_message_chunk", "user_message"})
TOOL_SESSION_UPDATES = frozenset({"tool_call", "tool_call_update"})
CONTEXT_HISTORY_METHOD = "_posthog/context_history"
CONTEXT_BLOCK_PREFIX = "<posthog_"
CONTEXT_HISTORY_MAX_BYTES = 256 * 1024
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
class HumanEntry:
    """A human message in a log part as the turn rule reads it: its index in the part, a digest of its text, and
    whether it is the ``_posthog/user_message`` form."""

    index: int
    text_key: str
    user_message: bool


@frozen
class LogPartSummary:
    """What one log part contributes to a slice, so a slice never reads a part that lies before it.

    ``state`` maps each state key to the last entry in the part that set it, as its index in the part and its
    line; ``requests`` holds the part's permission requests the same way, with their ids; ``resolved`` holds
    the request ids the part resolves. ``last_turn_complete`` is the index of its last turn completion, which
    closes every request before it. ``human`` lists the human messages that the turn rule reads, ``context``
    holds the texts of the user messages that carry context blocks, once each, and ``size`` is the byte size of
    the part's entries.
    """

    count: int
    state: dict[str, tuple[int, str]]
    requests: list[tuple[int, str, str]]
    resolved: frozenset[str]
    last_turn_complete: int | None = None
    human: tuple[HumanEntry, ...] = ()
    context: tuple[str, ...] = ()
    size: int = 0


@frozen
class LogPart:
    """One storage object of a resume-chain log: its summary, and its entries, which load on first use."""

    summary: LogPartSummary
    entries: Callable[[], list[str]]


def log_entries(content: str) -> list[str]:
    return [line for line in content.split("\n") if line.strip().startswith("{")]


def log_part(entries: list[str]) -> LogPart:
    return LogPart(summary=summarize_log_part(entries), entries=lambda: entries)


def _entry(line: str) -> dict:
    try:
        entry = json.loads(line)
    except ValueError:
        return {}
    return entry if isinstance(entry, dict) else {}


def _notification(line: str) -> dict:
    notification = _entry(line).get("notification")
    return notification if isinstance(notification, dict) else {}


def _method(notification: dict) -> str | None:
    method = notification.get("method")
    return method if isinstance(method, str) else None


def _session_update(notification: dict) -> dict:
    params = notification.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    return update if isinstance(update, dict) else {}


def _session_update_type(notification: dict) -> str | None:
    session_update = _session_update(notification).get("sessionUpdate")
    return session_update if isinstance(session_update, str) else None


def _is_user_entry(line: str) -> bool:
    """Any entry of a user message, in either wire form, including a hidden prompt and an attached file."""
    if "user_message" not in line:
        return False
    notification = _notification(line)
    method = _method(notification)
    if method == USER_MESSAGE_METHOD:
        return True
    return method == "session/update" and _session_update_type(notification) in USER_SESSION_UPDATES


def _is_prompt(line: str) -> bool:
    return PROMPT_METHOD in line and _method(_notification(line)) == PROMPT_METHOD


def _human_entry(index: int, line: str) -> HumanEntry | None:
    if "user_message" not in line:
        return None
    notification = _notification(line)
    params = notification.get("params")
    human = human_text(_method(notification), params if isinstance(params, dict) else {})
    if human is None or not is_turn_text(human.text):
        return None
    return HumanEntry(
        index=index, text_key=hashlib.sha256(human.text.encode()).hexdigest(), user_message=human.user_message
    )


@frozen
class EchoSpan:
    """A ``_posthog/user_message`` at ``first`` and the later ``session/update`` form of it at ``last``. A cut in
    ``(first, last]`` separates the two."""

    first: int
    last: int


@frozen
class ToolFrame:
    """A tool call frame: ``tool_call`` or ``tool_call_update``, its call id, and the call id of its parent."""

    kind: str
    call_id: str
    parent: str | None


def _tool_frame(line: str) -> ToolFrame | None:
    if '"tool_call' not in line:
        return None
    notification = _notification(line)
    if _method(notification) != "session/update":
        return None
    update = _session_update(notification)
    kind = update.get("sessionUpdate")
    call_id = update.get("toolCallId")
    if kind not in TOOL_SESSION_UPDATES or not isinstance(call_id, str) or not call_id:
        return None
    meta = update.get("_meta")
    claude_code = meta.get("claudeCode") if isinstance(meta, dict) else None
    parent = claude_code.get("parentToolCallId") if isinstance(claude_code, dict) else None
    return ToolFrame(kind=str(kind), call_id=call_id, parent=parent if isinstance(parent, str) and parent else None)


def _context_text(notification: dict) -> str | None:
    """The text of a user message that starts with context blocks. The client reads the block lines from it to
    dedupe the context it sends, so a page that starts after the message still knows that context."""
    method = _method(notification)
    params = notification.get("params")
    if not isinstance(params, dict):
        return None
    text: object = None
    if method == USER_MESSAGE_METHOD:
        content = params.get("content")
        if isinstance(content, list):
            text = "".join(
                block["text"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
        else:
            text = content
    elif method == "session/update" and _session_update_type(notification) == "user_message":
        update = _session_update(notification)
        content = update.get("content")
        text = content.get("text") if isinstance(content, dict) else update.get("text")
    return text if isinstance(text, str) and text.startswith(CONTEXT_BLOCK_PREFIX) else None


def _request_id(notification: dict) -> str | None:
    params = notification.get("params")
    request_id = params.get("requestId") if isinstance(params, dict) else None
    return request_id if isinstance(request_id, str) else None


def _state_keys(notification: dict) -> list[str]:
    """The state keys an entry sets. Usage folds field by field, so each usage field is its own key."""
    method = _method(notification)
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
    human: list[HumanEntry] = []
    context: dict[str, None] = {}
    for index, line in enumerate(entries):
        if not any(marker in line for marker in STATE_MARKERS):
            continue
        if (human_entry := _human_entry(index, line)) is not None:
            human.append(human_entry)
        notification = _notification(line)
        if CONTEXT_BLOCK_PREFIX in line and (text := _context_text(notification)) is not None:
            context[text] = None
        method = _method(notification)
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
        human=tuple(human),
        context=tuple(context),
        size=sum(len(line) + 1 for line in entries),
    )


def summary_to_json(summary: LogPartSummary) -> str:
    return json.dumps(
        {
            "count": summary.count,
            "state": {key: [index, line] for key, (index, line) in summary.state.items()},
            "requests": [list(request) for request in summary.requests],
            "resolved": sorted(summary.resolved),
            "last_turn_complete": summary.last_turn_complete,
            "human": [[entry.index, entry.text_key, entry.user_message] for entry in summary.human],
            "context": list(summary.context),
            "size": summary.size,
        }
    )


def summary_from_json(text: object) -> LogPartSummary | None:
    """The summary that ``summary_to_json`` wrote, or ``None`` when the value has another shape."""
    if not isinstance(text, str):
        return None
    try:
        data = json.loads(text)
        return LogPartSummary(
            count=int(data["count"]),
            state={str(key): (int(index), str(line)) for key, (index, line) in data["state"].items()},
            requests=[(int(index), str(request_id), str(line)) for index, request_id, line in data["requests"]],
            resolved=frozenset(str(request_id) for request_id in data["resolved"]),
            last_turn_complete=None if data["last_turn_complete"] is None else int(data["last_turn_complete"]),
            human=tuple(
                HumanEntry(index=int(index), text_key=str(text_key), user_message=bool(user_message))
                for index, text_key, user_message in data["human"]
            ),
            context=tuple(str(message) for message in data["context"]),
            size=int(data["size"]),
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


class _Chain:
    """The parts of a resume-chain log, read by full-log index. A part's entries load only when a read needs them."""

    def __init__(self, parts: Sequence[LogPart]) -> None:
        self._parts = parts
        self._loaded: dict[int, list[str]] = {}
        self.starts: list[int] = []
        total = 0
        for part in parts:
            self.starts.append(total)
            total += part.summary.count
        self.count = total
        self._human = [
            (self.starts[part_index] + entry.index, entry)
            for part_index, part in enumerate(parts)
            for entry in part.summary.human
        ]
        self._echo_spans = self._unsafe_echo_spans()
        self._echo_firsts = [span.first for span in self._echo_spans]

    def _entries(self, part_index: int) -> list[str]:
        if part_index not in self._loaded:
            self._loaded[part_index] = self._parts[part_index].entries()
        return self._loaded[part_index]

    def lines_backward(self, end: int) -> Iterator[tuple[int, str]]:
        for part_index in range(len(self._parts) - 1, -1, -1):
            start = self.starts[part_index]
            if start >= end:
                continue
            entries = self._entries(part_index)
            last = min(self._parts[part_index].summary.count, len(entries), end - start)
            for local in range(last - 1, -1, -1):
                yield start + local, entries[local]

    def lines(self, begin: int, end: int) -> list[str]:
        lines: list[str] = []
        for part_index, part in enumerate(self._parts):
            start = self.starts[part_index]
            stop = start + part.summary.count
            if stop <= begin or start >= end:
                continue
            lines += self._entries(part_index)[max(begin - start, 0) : min(end, stop) - start]
        return lines

    def size_after_part_of(self, index: int) -> int:
        """The byte size of the parts that start after the part that holds ``index``."""
        return sum(part.summary.size for part_index, part in enumerate(self._parts) if self.starts[part_index] > index)

    def turns_before(self, cut: int) -> int:
        counter = HumanTurnCounter()
        return sum(
            1 for index, entry in self._human if index < cut and counter.opens_turn(entry.text_key, entry.user_message)
        )

    def _unsafe_echo_spans(self) -> list[EchoSpan]:
        """The spans where a cut separates a ``_posthog/user_message`` from the later ``session/update`` form that
        ``HumanTurnCounter`` pairs with it, merged and sorted. Each later form spends the newest credit of its
        text, which keeps the same counts the counter keeps."""
        credits: defaultdict[str, list[int]] = defaultdict(list)
        spans: list[tuple[int, int]] = []
        for index, entry in self._human:
            if entry.user_message:
                credits[entry.text_key].append(index)
            elif credits[entry.text_key]:
                # The newest credit: an older message whose echo never came leaves a credit the counter never spends.
                spans.append((credits[entry.text_key].pop(), index))
        merged: list[EchoSpan] = []
        for first, last in sorted(spans):
            if merged and first < merged[-1].last:
                merged[-1] = EchoSpan(first=merged[-1].first, last=max(merged[-1].last, last))
            else:
                merged.append(EchoSpan(first=first, last=last))
        return merged

    def echo_safe(self, cut: int) -> bool:
        """Whether the turn rule reads every human message from ``cut`` on the same way with or without the
        messages before it. A ``_posthog/user_message`` before the cut whose echo comes after the cut fails."""
        position = bisect.bisect_left(self._echo_firsts, cut) - 1
        return position < 0 or not (self._echo_spans[position].first < cut <= self._echo_spans[position].last)

    def preamble(self, cut: int) -> list[str]:
        """The entries before ``cut`` that still set run state there: the latest entry for each state key (run
        start, SDK session, starting mode, mode, commands, each usage field) and the permission requests that
        nobody resolved. A synthetic ``_posthog/context_history`` entry carries the context-block messages before
        the cut, newest kept within ``CONTEXT_HISTORY_MAX_BYTES``."""
        summaries = [part.summary for part in self._parts]
        resolved = frozenset().union(*(summary.resolved for summary in summaries))
        # A turn completion closes every request before it, resolved or not.
        closed_before = max(
            (
                self.starts[part_index] + summary.last_turn_complete
                for part_index, summary in enumerate(summaries)
                if summary.last_turn_complete is not None
            ),
            default=-1,
        )
        latest: dict[str, tuple[int, str]] = {}
        requests: list[tuple[int, str]] = []
        context: dict[str, None] = {}
        for part_index, summary in enumerate(summaries):
            start = self.starts[part_index]
            if start >= cut:
                break
            if start + summary.count > cut:
                summary = summarize_log_part(self._entries(part_index)[: cut - start])
            for key, (index, line) in summary.state.items():
                latest[key] = (start + index, line)
            requests += [
                (start + index, line)
                for index, request_id, line in summary.requests
                if request_id not in resolved and start + index > closed_before
            ]
            for message in summary.context:
                context.pop(message, None)
                context[message] = None
        lines = [line for _, line in sorted({*latest.values(), *requests})]
        messages: list[str] = []
        size = 0
        for message in reversed(context):
            size += len(message)
            if size > CONTEXT_HISTORY_MAX_BYTES:
                break
            messages.insert(0, message)
        if messages:
            history = {"method": CONTEXT_HISTORY_METHOD, "params": {"messages": messages}}
            lines.insert(0, json.dumps({"type": "notification", "notification": history}))
        return lines


def _find_cut(chain: _Chain, end: int, tail_bytes: int) -> int:
    """The latest safe cut that leaves at least ``tail_bytes`` before ``end``, or 0 when the log has none.

    A cut starts a user turn: the first user entry of a run of user entries and prompts, so both wire forms of
    one message stay on one side. A turn that grows past ``TAIL_TURN_SLACK_FACTOR`` times the budget can be
    cut before a top-level tool call instead. A cut is safe when every tool frame after it has its call, and
    its parent's call, after it too, and when the turn rule reads the messages after it the same way.
    """
    cap = tail_bytes * TAIL_TURN_SLACK_FACTOR
    size = 0
    started: set[str] = set()
    missing: set[str] = set()
    turn_start: int | None = None
    tool_cut: int | None = None

    def safe(index: int) -> bool:
        return not missing and chain.echo_safe(index)

    for index, line in chain.lines_backward(end):
        if _is_user_entry(line):
            turn_start = index
        elif turn_start is not None and not _is_prompt(line):
            if size >= tail_bytes and safe(turn_start):
                return turn_start
            turn_start = None
        size += len(line) + 1
        if (frame := _tool_frame(line)) is not None:
            if frame.kind == "tool_call":
                started.add(frame.call_id)
                missing.discard(frame.call_id)
            elif frame.call_id not in started:
                missing.add(frame.call_id)
            if frame.parent is not None and frame.parent not in started:
                missing.add(frame.parent)
            top_level_call = frame.kind == "tool_call" and frame.parent is None
            if top_level_call and tool_cut is None and size >= tail_bytes and safe(index):
                tool_cut = index
        if size > cap and tool_cut is not None:
            return tool_cut
    return 0


def _join(entries: Sequence[str]) -> str:
    return "".join(f"{entry}\n" for entry in entries)


def _tail(chain: _Chain, tail_bytes: int, before: int | None) -> LogSlice:
    end = chain.count if before is None else min(max(before, 0), chain.count)
    cut = _find_cut(chain, end, tail_bytes)
    preamble = chain.preamble(cut) if cut else []
    return LogSlice(
        content=_join([*preamble, *chain.lines(cut, end)]),
        offset=cut,
        count=chain.count,
        preamble=len(preamble),
        turns_before=chain.turns_before(cut),
    )


def slice_log_parts_tail(parts: Sequence[LogPart], tail_bytes: int, before: int | None = None) -> LogSlice:
    """The latest entries of a multi-part JSONL log, from the latest safe cut (see ``_find_cut``).

    ``before`` ends the window at that entry index, so a client can page back through older turns. ``offset``
    is the index of the first returned entry in the full log, the same index that ``log-N`` stream cursors use.
    The slice starts with ``preamble`` entries from before the cut that still set run state there. Only the
    parts that overlap the window are read; the parts before it contribute through their summaries.
    """
    return _tail(_Chain(parts), tail_bytes, before)


def slice_log_parts_from(
    parts: Sequence[LogPart], start: int, tail_bytes: int, max_bytes: int = START_READ_MAX_BYTES
) -> LogSlice:
    """Every entry from index ``start`` to the end, with no preamble, for a client that holds the entries
    before ``start``. When they are more than ``max_bytes``, the latest entries as ``slice_log_parts_tail``
    returns them, so the client starts again from them."""
    chain = _Chain(parts)
    start = min(max(start, 0), chain.count)
    if chain.size_after_part_of(start) <= max_bytes:
        lines = chain.lines(start, chain.count)
        if sum(len(line) + 1 for line in lines) <= max_bytes:
            return LogSlice(
                content=_join(lines), offset=start, count=chain.count, turns_before=chain.turns_before(start)
            )
    tail = _tail(chain, tail_bytes, None)
    if tail.offset > start:
        return tail
    return LogSlice(
        content=_join(chain.lines(start, chain.count)),
        offset=start,
        count=chain.count,
        turns_before=chain.turns_before(start),
    )


def slice_log_tail(content: str, tail_bytes: int, before: int | None = None) -> LogSlice:
    """``slice_log_parts_tail`` over a log held in one string."""
    return slice_log_parts_tail([log_part(log_entries(content))], tail_bytes, before)


def slice_log_from(content: str, start: int, tail_bytes: int, max_bytes: int = START_READ_MAX_BYTES) -> LogSlice:
    """``slice_log_parts_from`` over a log held in one string."""
    return slice_log_parts_from([log_part(log_entries(content))], start, tail_bytes, max_bytes)
