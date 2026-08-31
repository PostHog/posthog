"""Read bounded, completed PostHog MCP calls from persisted task-run ACP logs.

This is a Tasks-owned transport boundary. It reconstructs generic PostHog MCP
calls without deciding whether a particular tool or result is useful to a
consumer. Callers must validate the returned tool name, arguments, and result
against their own domain contract.
"""

import re
import json
from collections.abc import Iterable
from datetime import datetime
from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware, make_aware

from posthog.dataclasses import frozen

from products.tasks.backend.facade import contracts
from products.tasks.backend.models import TaskRun

MAX_COMPLETED_POSTHOG_MCP_TOOL_CALLS = 64
MAX_RUN_LOG_CHARS = 4 * 1024 * 1024
MAX_LOG_LINE_CHARS = 256 * 1024
MAX_TOOL_ARGUMENT_BYTES = 32 * 1024
MAX_TOOL_RESULT_BYTES = 128 * 1024

_POSTHOG_TOOL_PREFIX = "mcp__posthog__"
_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,199}$")
_EXEC_COMMAND_PATTERN = re.compile(r"^call\s+(?:(--json)\s+)?([^\s]+)\s+(.+)$", re.DOTALL)


@frozen
class _ParsedToolResult:
    output: dict[str, object]
    is_error: bool
    is_truncated: bool


def get_completed_posthog_mcp_tool_calls(
    *, task_run_id: UUID | str, task_id: UUID | str, team_id: int
) -> list[contracts.CompletedPostHogMCPToolCallDTO]:
    """Return bounded completed PostHog MCP calls for exactly one team-scoped run.

    Missing storage, malformed log entries, non-completed calls, and oversized
    candidates are deliberately indistinguishable from no matching calls. This
    prevents an incomplete transcript from becoming evidence in another product.
    """
    try:
        run = TaskRun.objects.filter(id=task_run_id, task_id=task_id, team_id=team_id).first()
    except (TypeError, ValueError, DjangoValidationError):
        return []
    if run is None or run.status != TaskRun.Status.COMPLETED:
        return []

    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the facade import path

    try:
        log = object_storage.read(run.log_url, missing_ok=True)
    except Exception:
        return []
    if not isinstance(log, str) or len(log) > MAX_RUN_LOG_CHARS:
        return []

    starts: dict[str, dict[str, object]] = {}
    calls: list[contracts.CompletedPostHogMCPToolCallDTO] = []
    completed_ids: set[str] = set()
    for entry in _jsonl_entries(log):
        update = _acp_update(entry)
        if update is None:
            continue
        session_update = update.get("sessionUpdate")
        tool_call_id = update.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id or len(tool_call_id) > 200:
            continue
        if session_update == "tool_call":
            starts[tool_call_id] = update
            continue
        if session_update != "tool_call_update" or update.get("status") != "completed" or tool_call_id in completed_ids:
            continue

        completed_ids.add(tool_call_id)
        completed_at = _entry_timestamp(entry)
        if completed_at is None:
            continue
        call = _completed_call(
            tool_call_id=tool_call_id,
            update=update,
            start=starts.get(tool_call_id),
            completed_at=completed_at,
        )
        if call is not None:
            calls.append(call)
            if len(calls) == MAX_COMPLETED_POSTHOG_MCP_TOOL_CALLS:
                break
    return calls


def _jsonl_entries(log: str) -> Iterable[dict[str, object]]:
    for line in log.splitlines():
        if not line or len(line) > MAX_LOG_LINE_CHARS:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield cast(dict[str, object], parsed)


def _acp_update(entry: dict[str, object]) -> dict[str, object] | None:
    notification = entry.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != "session/update":
        return None
    params = notification.get("params")
    if not isinstance(params, dict):
        return None
    update = params.get("update")
    return cast(dict[str, object], update) if isinstance(update, dict) else None


def _entry_timestamp(entry: dict[str, object]) -> datetime | None:
    raw_timestamp = entry.get("timestamp")
    if not isinstance(raw_timestamp, str):
        return None
    timestamp = parse_datetime(raw_timestamp)
    if timestamp is None:
        return None
    return timestamp if is_aware(timestamp) else make_aware(timestamp)


def _completed_call(
    *,
    tool_call_id: str,
    update: dict[str, object],
    start: dict[str, object] | None,
    completed_at: datetime,
) -> contracts.CompletedPostHogMCPToolCallDTO | None:
    raw_input = _raw_input(update, start)
    if raw_input is None:
        return None

    direct_tool_name = _direct_posthog_tool_name(update, start)
    if direct_tool_name is not None:
        arguments = _direct_arguments(raw_input)
        if arguments is None:
            return None
        result = _call_tool_result(update, start)
        if result is None:
            return None
        if not _within_json_budget(arguments, MAX_TOOL_ARGUMENT_BYTES) or not _within_json_budget(
            result.output, MAX_TOOL_RESULT_BYTES
        ):
            return None
        return contracts.CompletedPostHogMCPToolCallDTO(
            tool_call_id=tool_call_id,
            tool_name=direct_tool_name,
            arguments=arguments,
            result=result.output,
            completed_at=completed_at,
            is_error=result.is_error,
            is_truncated=result.is_truncated,
        )

    command = raw_input.get("command")
    if not isinstance(command, str):
        return None
    executable = _parse_json_exec_command(command)
    if executable is None:
        return None
    tool_name, arguments = executable
    result = _exec_result(update, start)
    if result is None:
        return None
    if (
        result.is_error
        or not _within_json_budget(arguments, MAX_TOOL_ARGUMENT_BYTES)
        or not _within_json_budget(result.output, MAX_TOOL_RESULT_BYTES)
    ):
        return None
    return contracts.CompletedPostHogMCPToolCallDTO(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        result=result.output,
        completed_at=completed_at,
        is_error=False,
        is_truncated=result.is_truncated,
    )


def _raw_input(update: dict[str, object], start: dict[str, object] | None) -> dict[str, object] | None:
    empty_input: dict[str, object] | None = None
    for event in (update, start):
        if event is None:
            continue
        raw_input = event.get("rawInput")
        if isinstance(raw_input, dict):
            normalized_input = cast(dict[str, object], raw_input)
            if normalized_input:
                return normalized_input
            empty_input = normalized_input
    return empty_input


def _direct_posthog_tool_name(update: dict[str, object], start: dict[str, object] | None) -> str | None:
    """Read a direct tool identity from ACP's agent-provided metadata only."""
    for event in (update, start):
        if event is None:
            continue
        meta = event.get("_meta")
        if isinstance(meta, dict):
            claude_code = meta.get("claudeCode")
            if isinstance(claude_code, dict):
                candidate = claude_code.get("toolName")
                if not isinstance(candidate, str) or not candidate.startswith(_POSTHOG_TOOL_PREFIX):
                    continue
                tool_name = candidate.removeprefix(_POSTHOG_TOOL_PREFIX)
                if _TOOL_NAME_PATTERN.fullmatch(tool_name):
                    return tool_name
    return None


def _direct_arguments(raw_input: dict[str, object]) -> dict[str, object] | None:
    if "arguments" in raw_input or "input" in raw_input:
        return _json_object(raw_input.get("arguments", raw_input.get("input")))
    return _json_object(raw_input)


def _parse_json_exec_command(command: str) -> tuple[str, dict[str, object]] | None:
    match = _EXEC_COMMAND_PATTERN.fullmatch(command.strip())
    if match is None or match.group(1) != "--json":
        return None
    tool_name = match.group(2)
    if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
        return None
    arguments = _json_object(match.group(3))
    return (tool_name, arguments) if arguments is not None else None


def _call_tool_result(update: dict[str, object], start: dict[str, object] | None) -> _ParsedToolResult | None:
    for source in (update.get("rawOutput"), update.get("content"), start.get("rawOutput") if start else None):
        for candidate in _result_candidates(source):
            parsed = _parse_call_tool_result(candidate)
            if parsed is not None:
                return parsed
    return None


def _exec_result(update: dict[str, object], start: dict[str, object] | None) -> _ParsedToolResult | None:
    for source in (update.get("rawOutput"), update.get("content"), start.get("rawOutput") if start else None):
        for candidate in _result_candidates(source):
            wrapped = _parse_call_tool_result(candidate)
            if wrapped is not None:
                return wrapped
            raw = _raw_json_result(candidate)
            if raw is not None:
                return _ParsedToolResult(output=raw, is_error=False, is_truncated=False)
    return None


def _raw_json_result(candidate: object) -> dict[str, object] | None:
    parsed = _json_object(candidate)
    if parsed is None:
        return None
    if parsed.get("type") == "text":
        return _json_object(parsed.get("text"))
    return parsed


def _result_candidates(source: object) -> Iterable[object]:
    if isinstance(source, list):
        yield from source
    elif source is not None:
        yield source


def _parse_call_tool_result(candidate: object) -> _ParsedToolResult | None:
    object_candidate = _json_object(candidate)
    if object_candidate is None:
        return None
    if object_candidate.get("type") == "text":
        return _parse_call_tool_result(object_candidate.get("text"))
    is_error = object_candidate.get("isError") is True
    is_truncated = object_candidate.get("isTruncated") is True
    structured = _json_object(object_candidate.get("structuredContent"))
    if structured is not None:
        return _ParsedToolResult(output=structured, is_error=is_error, is_truncated=is_truncated)
    content = object_candidate.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        parsed = _json_object(block.get("text"))
        if parsed is not None:
            return _ParsedToolResult(output=parsed, is_error=is_error, is_truncated=is_truncated)
    return None


def _json_object(value: object) -> dict[str, object] | None:
    parsed: object
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        parsed = value
    return cast(dict[str, object], parsed) if isinstance(parsed, dict) else None


def _within_json_budget(value: dict[str, object], limit: int) -> bool:
    try:
        return len(json.dumps(value, separators=(",", ":")).encode()) <= limit
    except (TypeError, ValueError, OverflowError):
        return False
