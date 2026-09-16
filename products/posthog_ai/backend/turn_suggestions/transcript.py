"""Compact transcript of a sandbox conversation's latest turn, folded from raw agent-run stream frames.

The stream carries every ACP frame the agent-server emitted. The turn classifier only needs three
things from it: what the user asked, what the assistant answered, and which PostHog tools ran with
their inner names resolved out of the single-exec ``mcp__posthog__exec`` wrapper.
"""

import re
import json
from collections.abc import Iterable
from typing import Any

from posthog.dataclasses import frozen

from products.posthog_ai.backend.wire_types import NotificationFrame, is_user_message_params, parse_log_entry
from products.posthog_ai.eval_harness.log_parser import INFO_SYNTHETIC_PREFIX, normalize_tool_name, parse_exec_command

POSTHOG_EXEC_TOOL_RE = re.compile(r"^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$")

# The send path prefixes user text with context blocks the user never sees. The legacy
# ``<posthog_context>`` wrapper still appears in older histories.
_CONTEXT_BLOCK_RE = re.compile(
    r"\A\s*<(posthog_trusted_context|posthog_untrusted_context|posthog_context)>.*?</\1>\s*",
    re.DOTALL,
)

TOOL_ARGS_PREVIEW_LIMIT = 400
ASSISTANT_TEXT_LIMIT = 6000
_TOOL_ARGS_PREVIEW_KEYS = ("command", "code", "query", "pattern", "url", "description", "prompt", "name", "title")


@frozen
class TranscriptToolCall:
    name: str
    args_preview: str
    status: str
    from_posthog: bool


@frozen
class TurnTranscript:
    human_messages: tuple[str, ...]
    assistant_text: str
    tool_calls: tuple[TranscriptToolCall, ...]

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


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
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


def _agent_tool_name(update: dict[str, Any]) -> str:
    meta = update.get("_meta")
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
    accumulator.name = tool
    accumulator.args_preview = _args_preview(inner_input) if inner_input else ""


def build_turn_transcript(entries: Iterable[dict[str, Any]]) -> TurnTranscript:
    """Fold stream entries into the transcript of the turn after the last user message.

    Human messages come from ``_posthog/user_message`` frames, which is also what the thread renders.
    A stream without any of them falls back to ``session/prompt`` requests so an older run still
    counts its turns.
    """
    human_messages: list[str] = []
    prompt_fallbacks: list[str] = []
    # Assistant text by message id, in arrival order. Chunks append; a closing `agent_message`
    # carries the whole text and replaces them, matching how the thread fold finalizes a bubble.
    assistant_messages: dict[str, str] = {}
    tool_calls: dict[str, _ToolCallAccumulator] = {}

    def start_turn(text: str) -> None:
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

    for entry in entries:
        frame = parse_log_entry(entry)
        if not isinstance(frame, NotificationFrame):
            continue
        method = frame.notification.method
        params = frame.notification.params if isinstance(frame.notification.params, dict) else {}

        if is_user_message_params(params, method):
            text = strip_context_blocks(_text_from_content(params.get("content")))
            if text:
                start_turn(text)
            continue
        if method == "session/prompt":
            text = strip_context_blocks(_text_from_content(params.get("prompt")))
            if text:
                prompt_fallbacks.append(text)
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
                name=None, args_preview="", status="pending", from_posthog=False, discovery=False
            )
            tool_calls[tool_call_id] = accumulator
        if accumulator.name is None or (accumulator.from_posthog and not accumulator.args_preview):
            _resolve_tool(update, accumulator)
        status = update.get("status")
        if isinstance(status, str) and status:
            accumulator.status = status

    if not human_messages and prompt_fallbacks:
        human_messages = prompt_fallbacks

    return TurnTranscript(
        human_messages=tuple(human_messages),
        assistant_text=truncate_text(
            "\n\n".join(text for text in assistant_messages.values() if text),
            ASSISTANT_TEXT_LIMIT,
            collapse_whitespace=False,
        ),
        tool_calls=tuple(
            TranscriptToolCall(
                name=accumulator.name or "unknown",
                args_preview=accumulator.args_preview,
                status=accumulator.status,
                from_posthog=accumulator.from_posthog,
            )
            for accumulator in tool_calls.values()
            if not accumulator.discovery
        ),
    )
