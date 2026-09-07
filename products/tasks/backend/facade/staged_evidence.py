"""Bounded evidence reconstructed from one staged task's persisted ACP log."""

from __future__ import annotations

import re
import json
from typing import TYPE_CHECKING, cast

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

_MAX_LOG_BYTES = 2 * 1024 * 1024
_MAX_LOG_LINE_CHARS = 64 * 1024
_MAX_CALLS = 32
_MAX_RESULT_BYTES = 64 * 1024
_POSTHOG_TOOL_PREFIX = "mcp__posthog__"
_TOOL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_EXEC_COMMAND_PATTERN = re.compile(r"^call --json ([^\s]+) (.+)$", re.DOTALL)


@frozen
class CompletedMCPCallEvidence:
    citation_id: str
    tool_name: str
    result: dict[str, object]


def parse_completed_posthog_mcp_calls(log: str) -> tuple[CompletedMCPCallEvidence, ...]:
    """Return completed, bounded PostHog calls; malformed log material is not evidence."""

    if len(log.encode("utf-8")) > _MAX_LOG_BYTES:
        return ()

    starts: dict[str, dict[str, object]] = {}
    completed_ids: set[str] = set()
    calls: list[CompletedMCPCallEvidence] = []
    for entry in _entries(log):
        update = _session_update(entry)
        if update is None:
            continue
        tool_call_id = update.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id or len(tool_call_id) > 200:
            continue
        if update.get("sessionUpdate") == "tool_call":
            if len(starts) < _MAX_CALLS:
                starts[tool_call_id] = update
            continue
        if (
            update.get("sessionUpdate") != "tool_call_update"
            or update.get("status") != "completed"
            or tool_call_id in completed_ids
        ):
            continue
        completed_ids.add(tool_call_id)
        call = _completed_call(tool_call_id, update, starts.get(tool_call_id))
        if call is not None:
            calls.append(call)
            if len(calls) == _MAX_CALLS:
                break
    return tuple(calls)


def read_completed_posthog_mcp_calls(run: TaskRun) -> tuple[CompletedMCPCallEvidence, ...]:
    """Read one completed run's immutable log without surfacing storage errors."""

    from posthog.storage import object_storage  # noqa: PLC0415 - keeps object storage off the facade import path

    try:
        log = object_storage.read(run.log_url, missing_ok=True)
    except Exception:
        return ()
    return parse_completed_posthog_mcp_calls(log) if isinstance(log, str) else ()


def _entries(log: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for line in log.splitlines():
        if not line or len(line) > _MAX_LOG_LINE_CHARS:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(cast(dict[str, object], parsed))
    return entries


def _session_update(entry: dict[str, object]) -> dict[str, object] | None:
    notification = entry.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != "session/update":
        return None
    params = notification.get("params")
    if not isinstance(params, dict):
        return None
    update = params.get("update")
    return cast(dict[str, object], update) if isinstance(update, dict) else None


def _completed_call(
    tool_call_id: str, update: dict[str, object], start: dict[str, object] | None
) -> CompletedMCPCallEvidence | None:
    raw_input = _raw_input(update, start)
    if raw_input is None:
        return None
    tool_name = _direct_tool_name(update, start)
    if tool_name is None:
        command = raw_input.get("command")
        if not isinstance(command, str):
            return None
        match = _EXEC_COMMAND_PATTERN.fullmatch(command.strip())
        if match is None or not _TOOL_NAME_PATTERN.fullmatch(match.group(1)) or _json_object(match.group(2)) is None:
            return None
        tool_name = match.group(1)
    result = _result(update, start)
    if result is None or not _within_result_budget(result):
        return None
    return CompletedMCPCallEvidence(citation_id=f"mcp:{tool_call_id}", tool_name=tool_name, result=result)


def _raw_input(update: dict[str, object], start: dict[str, object] | None) -> dict[str, object] | None:
    for event in (update, start):
        if event is None:
            continue
        candidate = event.get("rawInput")
        if isinstance(candidate, dict):
            return cast(dict[str, object], candidate)
    return None


def _direct_tool_name(update: dict[str, object], start: dict[str, object] | None) -> str | None:
    for event in (update, start):
        if event is None:
            continue
        meta = event.get("_meta")
        claude_code = meta.get("claudeCode") if isinstance(meta, dict) else None
        candidate = claude_code.get("toolName") if isinstance(claude_code, dict) else None
        if isinstance(candidate, str) and candidate.startswith(_POSTHOG_TOOL_PREFIX):
            tool_name = candidate.removeprefix(_POSTHOG_TOOL_PREFIX)
            if _TOOL_NAME_PATTERN.fullmatch(tool_name):
                return tool_name
    return None


def _result(update: dict[str, object], start: dict[str, object] | None) -> dict[str, object] | None:
    for event in (update, start):
        if event is None:
            continue
        raw_output = event.get("rawOutput")
        candidates = raw_output if isinstance(raw_output, list) else [raw_output]
        for candidate in candidates:
            candidate_object = _json_object(candidate)
            if candidate_object is None:
                continue
            if candidate_object.get("type") == "text":
                candidate_object = _json_object(candidate_object.get("text"))
                if candidate_object is None:
                    continue
            if candidate_object.get("isError") is True or candidate_object.get("isTruncated") is True:
                return None
            structured = _json_object(candidate_object.get("structuredContent"))
            if structured is not None:
                return structured
            content = candidate_object.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue
                    text = _json_object(block.get("text"))
                    if text is not None:
                        return text
                return None
            return candidate_object
    return None


def _json_object(value: object) -> dict[str, object] | None:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return None
    return cast(dict[str, object], parsed) if isinstance(parsed, dict) else None


def _within_result_budget(result: dict[str, object]) -> bool:
    try:
        return len(json.dumps(result, separators=(",", ":")).encode("utf-8")) <= _MAX_RESULT_BYTES
    except (TypeError, ValueError, OverflowError):
        return False
