"""Compact transcript of a sandbox conversation's latest turn, folded from raw agent-run stream frames.

The stream carries every ACP frame the agent-server emitted. The turn classifier only needs three
things from it: what the user asked, what the assistant answered, and which PostHog tools ran with
their inner names resolved out of the single-exec ``mcp__posthog__exec`` wrapper.
"""

import re
import json
from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any

from posthog.dataclasses import frozen

from products.posthog_ai.backend.exec_commands import INFO_SYNTHETIC_PREFIX, normalize_tool_name, parse_exec_command
from products.posthog_ai.backend.wire_types import NotificationFrame, is_user_message_params, parse_log_entry

POSTHOG_EXEC_TOOL_RE = re.compile(r"^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$")
# The PostHog MCP server puts a tool's handler payload here; its text content is a lossy rendering.
MCP_APP_DATA_META_KEY = "com.posthog.mcp/app_data"

# The send path prefixes user text with context blocks the user never sees. The legacy
# ``<posthog_context>`` wrapper still appears in older histories.
_CONTEXT_BLOCK_RE = re.compile(
    r"\A\s*<(posthog_trusted_context|posthog_untrusted_context|posthog_context)>.*?</\1>\s*",
    re.DOTALL,
)

# Masks the values an answer reports while keeping its shape: "412 signups, down 8%" reads as
# "<n> signups, down <n>%". A lookbehind skips digits inside identifiers such as `p95` or `v2`.
_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w$])[$€£]?\d(?:[\d,.:/-]*\d)?")

TOOL_ARGS_PREVIEW_LIMIT = 400
ASSISTANT_TEXT_LIMIT = 6000
_TOOL_ARGS_PREVIEW_KEYS = ("command", "code", "query", "pattern", "url", "description", "prompt", "name", "title")


@frozen
class TranscriptToolCall:
    name: str
    args_preview: str
    status: str


@frozen
class EarlierTurn:
    question: str
    tool_names: tuple[str, ...]
    answer_excerpt: str


_ALERTABLE_INSIGHT_KINDS = frozenset({"TrendsQuery"})


@frozen
class SavedInsightRef:
    short_id: str
    insight_id: int | None
    name: str
    query_kind: str

    @property
    def alertable(self) -> bool:
        """The alert card configures a series threshold, which only a trends insight carries."""
        return self.query_kind in _ALERTABLE_INSIGHT_KINDS

    def to_params(self) -> dict:
        return {"insightShortId": self.short_id, "insightId": self.insight_id, "insightName": self.name}


@frozen
class ErrorIssueRef:
    issue_id: str
    name: str


@frozen
class TurnTranscript:
    human_messages: tuple[str, ...]
    assistant_text: str
    tool_calls: tuple[TranscriptToolCall, ...]
    earlier_turns: tuple[EarlierTurn, ...]
    saved_insights: tuple[SavedInsightRef, ...]
    error_issues: tuple[ErrorIssueRef, ...]

    @property
    def last_human_message(self) -> str:
        return self.human_messages[-1]


@frozen(frozen=False)
class _ToolCallAccumulator:
    name: str | None
    args_preview: str
    status: str
    from_posthog: bool
    discovery: bool
    output: Any


EARLIER_TURN_LIMIT = 5
ANSWER_EXCERPT_LIMIT = 300
_INSIGHT_TOOLS = frozenset({"insight-create", "insight-update", "insight-get", "insight-query"})
_ERROR_ISSUE_TOOLS = frozenset({"query-error-tracking-issues-list", "error-tracking-issue-get"})


def _is_hidden(content: Any) -> bool:
    meta = content.get("_meta") if isinstance(content, dict) else None
    ui = meta.get("ui") if isinstance(meta, dict) else None
    return isinstance(ui, dict) and ui.get("hidden") is True


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and not _is_hidden(block)
        ]
        return "".join(part for part in parts if part)
    return ""


def strip_context_blocks(text: str) -> str:
    stripped = text
    while True:
        without_block = _CONTEXT_BLOCK_RE.sub("", stripped, count=1)
        if without_block == stripped:
            return stripped.strip()
        stripped = without_block


def redact_values(text: str) -> str:
    """Replace the numbers, emails, links and ids in ``text`` with placeholders."""
    text = _URL_RE.sub("<url>", text)
    text = _EMAIL_RE.sub("<email>", text)
    text = _UUID_RE.sub("<id>", text)
    return _NUMBER_RE.sub("<n>", text)


def truncate_text(value: str, limit: int, *, collapse_whitespace: bool = True) -> str:
    text = " ".join(value.split()) if collapse_whitespace else value.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _args_preview(raw_input: Any) -> str:
    if not isinstance(raw_input, dict):
        return ""
    for key in _TOOL_ARGS_PREVIEW_KEYS:
        value = raw_input.get(key)
        if isinstance(value, str) and value.strip():
            return truncate_text(value, TOOL_ARGS_PREVIEW_LIMIT)
    try:
        return truncate_text(json.dumps(raw_input, ensure_ascii=False), TOOL_ARGS_PREVIEW_LIMIT)
    except (TypeError, ValueError):
        return ""


def _posthog_meta_tool_name(meta: Any) -> str | None:
    """The tool identity an adapter stamps on ``_meta.posthog``, the way the thread's tool resolver reads it."""
    posthog_meta = meta.get("posthog") if isinstance(meta, dict) else None
    if not isinstance(posthog_meta, dict):
        return None
    mcp = posthog_meta.get("mcp")
    if isinstance(mcp, dict):
        server, tool = mcp.get("server"), mcp.get("tool")
        if isinstance(server, str) and server and isinstance(tool, str) and tool:
            return f"mcp__{server}__{tool}"
    tool_name = posthog_meta.get("toolName")
    return tool_name if isinstance(tool_name, str) and tool_name else None


def _agent_tool_name(update: dict[str, Any]) -> str:
    meta = update.get("_meta")
    posthog_tool_name = _posthog_meta_tool_name(meta)
    if posthog_tool_name:
        return posthog_tool_name
    claude_meta = meta.get("claudeCode") if isinstance(meta, dict) else None
    tool_name = claude_meta.get("toolName") if isinstance(claude_meta, dict) else None
    if isinstance(tool_name, str) and tool_name:
        return tool_name
    server_name = update.get("serverName")
    raw_name = update.get("toolName") or update.get("title") or ""
    if isinstance(server_name, str) and server_name and isinstance(raw_name, str):
        return f"mcp__{server_name}__{raw_name}"
    return raw_name if isinstance(raw_name, str) else ""


def _resolve_tool(update: dict[str, Any], accumulator: _ToolCallAccumulator) -> None:
    """Fill the accumulator's name and args from a tool_call or tool_call_update frame.

    An exec command streams in over updates, so a frame without a parseable ``command`` leaves the
    name unresolved for a later frame to fill.
    """
    raw_input = update.get("rawInput")
    agent_tool_name = _agent_tool_name(update)
    # A tool_call_update carries no tool identity, so an exec call identified by its first frame
    # stays exec when its command arrives later.
    if not accumulator.from_posthog and not POSTHOG_EXEC_TOOL_RE.match(agent_tool_name):
        if accumulator.name is None and agent_tool_name:
            accumulator.name = normalize_tool_name(agent_tool_name)
        if raw_input and not accumulator.args_preview:
            accumulator.args_preview = _args_preview(raw_input)
        return

    accumulator.from_posthog = True
    command = raw_input.get("command") if isinstance(raw_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return
    parsed = parse_exec_command(command)
    if parsed is None or parsed[0].startswith(INFO_SYNTHETIC_PREFIX):
        # `tools`, `search`, `info` and `schema` only read the catalog and say nothing about the turn.
        accumulator.discovery = True
        return
    tool, inner_input = parsed
    # A `call` still streaming in also fails to parse, so a later complete frame clears the mark.
    accumulator.discovery = False
    accumulator.name = tool
    accumulator.args_preview = _args_preview(inner_input) if inner_input else ""


def _notifications(entries: Iterable[dict[str, Any]]) -> Iterator[tuple[str | None, dict[str, Any]]]:
    for entry in entries:
        frame = parse_log_entry(entry)
        if isinstance(frame, NotificationFrame):
            params = frame.notification.params
            yield frame.notification.method, params if isinstance(params, dict) else {}


# The synthetic prompt a resumed run starts with. The thread never renders it, so it is not a turn.
RESUME_CONTEXT_PREFIX = "You are resuming a previous conversation."


def _human_text(method: str | None, params: dict[str, Any]) -> tuple[str, bool] | None:
    """The user's text in a ``_posthog/user_message`` frame, paired with ``True``, or in a
    ``session/update`` user message, paired with ``False``. ``None`` for any other frame.

    These are the two forms the thread renders as a human message, so turn indexes match its trailers.
    """
    if is_user_message_params(params, method):
        return strip_context_blocks(_text_from_content(params.get("content"))), True
    if method != "session/update":
        return None
    update = params.get("update")
    if not isinstance(update, dict) or update.get("sessionUpdate") not in {"user_message", "user_message_chunk"}:
        return None
    content = update.get("content")
    if _is_hidden(content):
        return None
    text = content.get("text") if isinstance(content, dict) else None
    if not isinstance(text, str):
        text = update.get("text")
    return strip_context_blocks(text if isinstance(text, str) else ""), False


def build_turn_transcript(entries: Iterable[dict[str, Any]]) -> TurnTranscript:
    """Fold stream entries into the transcript of the turn after the last user message.

    Human messages are counted the way the thread counts them: a ``_posthog/user_message`` frame, or a
    ``session/update`` user message that does not repeat one, so a turn persisted in both wire forms
    counts once.
    """
    human_messages: list[str] = []
    remembered_texts: Counter[str] = Counter()
    earlier_turns: list[EarlierTurn] = []
    # Assistant text by message id, in arrival order. Chunks append; a closing `agent_message`
    # carries the whole text and replaces them, matching how the thread fold finalizes a bubble.
    assistant_messages: dict[str, str] = {}
    tool_calls: dict[str, _ToolCallAccumulator] = {}

    def start_turn(text: str) -> None:
        if human_messages:
            # The finished turn stays available as context for classifying the one that follows.
            earlier_turns.append(
                EarlierTurn(
                    question=human_messages[-1],
                    tool_names=tuple(
                        accumulator.name or "unknown"
                        for accumulator in tool_calls.values()
                        if not accumulator.discovery
                    ),
                    answer_excerpt=truncate_text(_join_messages(assistant_messages), ANSWER_EXCERPT_LIMIT),
                )
            )
        human_messages.append(text)
        assistant_messages.clear()
        tool_calls.clear()

    def record_assistant_text(update: dict[str, Any], text: str, *, final: bool) -> None:
        message_id = update.get("messageId")
        key = message_id if isinstance(message_id, str) and message_id else "current"
        if final:
            # The wire is not consistent about carrying the id on the chunks and on the finalize, so
            # a finalize closes the buffer its chunks opened: the idless one, or the last open one.
            if key not in assistant_messages and "current" in assistant_messages:
                assistant_messages.pop("current")
            elif key == "current" and assistant_messages:
                key = next(reversed(assistant_messages))
            assistant_messages[key] = text
            return
        assistant_messages[key] = assistant_messages.get(key, "") + text

    for method, params in _notifications(entries):
        human = _human_text(method, params)
        if human is not None:
            text, is_user_message = human
            if not text or text.startswith(RESUME_CONTEXT_PREFIX):
                continue
            if is_user_message:
                remembered_texts[text] += 1
            elif remembered_texts[text] > 0:
                remembered_texts[text] -= 1
                continue
            start_turn(text)
            continue
        if method != "session/update":
            continue

        update = params.get("update")
        if not isinstance(update, dict):
            continue
        kind = update.get("sessionUpdate")
        if kind in {"agent_message", "agent_message_chunk"}:
            content = update.get("content")
            chunk = content.get("text") if isinstance(content, dict) and content.get("type") == "text" else None
            if isinstance(chunk, str) and chunk:
                record_assistant_text(update, chunk, final=kind == "agent_message")
            continue
        if kind not in {"tool_call", "tool_call_update"}:
            continue
        tool_call_id = update.get("toolCallId")
        if not isinstance(tool_call_id, str):
            continue
        accumulator = tool_calls.get(tool_call_id)
        if accumulator is None:
            accumulator = _ToolCallAccumulator(
                name=None, args_preview="", status="pending", from_posthog=False, discovery=False, output=None
            )
            tool_calls[tool_call_id] = accumulator
        if accumulator.name is None or (accumulator.from_posthog and not accumulator.args_preview):
            _resolve_tool(update, accumulator)
        status = update.get("status")
        if isinstance(status, str) and status:
            accumulator.status = status
        if "rawOutput" in update:
            accumulator.output = update.get("rawOutput")

    active = [accumulator for accumulator in tool_calls.values() if not accumulator.discovery]
    return TurnTranscript(
        human_messages=tuple(human_messages),
        assistant_text=truncate_text(
            _join_messages(assistant_messages), ASSISTANT_TEXT_LIMIT, collapse_whitespace=False
        ),
        tool_calls=tuple(
            TranscriptToolCall(
                name=accumulator.name or "unknown",
                args_preview=accumulator.args_preview,
                status=accumulator.status,
            )
            for accumulator in active
        ),
        earlier_turns=tuple(earlier_turns[-EARLIER_TURN_LIMIT:]),
        saved_insights=tuple(_saved_insights(active)),
        error_issues=tuple(_error_issues(active)),
    )


def _join_messages(assistant_messages: dict[str, str]) -> str:
    return "\n\n".join(text for text in assistant_messages.values() if text)


_MCP_ENVELOPE_KEYS = frozenset({"content", "structuredContent", "isError", "_meta", "__execBuiltPayload"})


def _tool_output_record(accumulator: _ToolCallAccumulator) -> dict[str, Any] | None:
    """The handler payload a tool returned, unwrapped from its MCP envelope the way the thread's widgets read it."""
    output = accumulator.output
    if not isinstance(output, dict) or output.get("isError") is True or accumulator.status == "failed":
        return None
    meta = output.get("_meta")
    app_data = meta.get(MCP_APP_DATA_META_KEY) if isinstance(meta, dict) else None
    if isinstance(app_data, dict):
        return app_data
    structured = output.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    return None if output.keys() <= _MCP_ENVELOPE_KEYS else output


def _saved_insights(tool_calls: list[_ToolCallAccumulator]) -> list[SavedInsightRef]:
    """Saved insights the turn created or read, from the REST payload the insight tools return."""
    refs: dict[str, SavedInsightRef] = {}
    for accumulator in tool_calls:
        if accumulator.name not in _INSIGHT_TOOLS:
            continue
        output = _tool_output_record(accumulator)
        if output is None:
            continue
        short_id = output.get("short_id")
        query = output.get("query")
        if not isinstance(short_id, str) or not short_id or not isinstance(query, dict):
            continue
        source = query.get("source") if isinstance(query.get("source"), dict) else query
        kind = source.get("kind") if isinstance(source, dict) else None
        insight_id = output.get("id")
        name = output.get("name")
        refs[short_id] = SavedInsightRef(
            short_id=short_id,
            insight_id=insight_id if isinstance(insight_id, int) else None,
            name=name if isinstance(name, str) else "",
            query_kind=kind if isinstance(kind, str) else "",
        )
    return list(refs.values())


def _error_issues(tool_calls: list[_ToolCallAccumulator]) -> list[ErrorIssueRef]:
    """Error tracking issues the turn looked at, from the list and detail tool payloads."""
    refs: dict[str, ErrorIssueRef] = {}
    for accumulator in tool_calls:
        if accumulator.name not in _ERROR_ISSUE_TOOLS:
            continue
        output = _tool_output_record(accumulator)
        if output is None:
            continue
        results = output.get("results")
        candidates = results if isinstance(results, list) else [output]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            issue_id = candidate.get("id")
            if not isinstance(issue_id, str) or not issue_id:
                continue
            name = candidate.get("name")
            refs[issue_id] = ErrorIssueRef(issue_id=issue_id, name=name if isinstance(name, str) else "")
    return list(refs.values())
