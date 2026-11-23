"""Reads the import agent's latest action from its run log, so the progress dialog can show what the agent does."""

from __future__ import annotations

import re
import json
import datetime as dt
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from products.metrics.backend.facade.enums import AgentActivityKind

_POSTHOG_MCP_PREFIX = "mcp__posthog__"
_EXEC_CALL = re.compile(r"^\s*call\s+(?:--\S+\s+)*(?P<tool>[^\s{]+)\s*(?P<args>.*)$", re.DOTALL)
_TERMINAL_STATUSES = frozenset({"completed", "failed"})
_LOCAL_TOOLS = frozenset({"read", "grep", "glob", "ls", "bash"})
_LOCAL_KINDS = frozenset({"read", "search", "execute"})
_TOOL_KINDS: dict[str, AgentActivityKind] = {
    "metric-names-list": AgentActivityKind.SEARCHING_METRICS,
    "metric-attributes-list": AgentActivityKind.READING_LABELS,
    "metric-attribute-values-list": AgentActivityKind.READING_LABEL_VALUES,
    "query-metrics": AgentActivityKind.RUNNING_QUERY,
    "query-logs": AgentActivityKind.RUNNING_QUERY,
    "query-apm-spans": AgentActivityKind.RUNNING_QUERY,
    "metrics-dashboard-panels-validate": AgentActivityKind.CHECKING_PANELS,
    "logs-services-create": AgentActivityKind.EXPLORING_LOGS,
    "logs-attributes-list": AgentActivityKind.EXPLORING_LOGS,
    "logs-attribute-values-list": AgentActivityKind.EXPLORING_LOGS,
    "apm-services-list": AgentActivityKind.EXPLORING_TRACES,
    "apm-attributes-list": AgentActivityKind.EXPLORING_TRACES,
    "apm-attribute-values-list": AgentActivityKind.EXPLORING_TRACES,
}
_MAX_SUBJECT_LENGTH = 120


@dataclass(frozen=True, slots=True)
class AgentAction:
    kind: AgentActivityKind
    started_at: dt.datetime
    last_activity_at: dt.datetime
    subject: str | None = None
    panel_count: int | None = None


@dataclass(slots=True)
class _ToolCall:
    started_at: dt.datetime
    name: str
    tool_kind: str | None
    kind: AgentActivityKind
    subject: str | None
    panel_count: int | None
    ended_at: dt.datetime | None = None


def latest_agent_action(log_content: str) -> AgentAction | None:
    """The agent's latest action in a JSONL run log. Between tool calls the model writes, so that time is THINKING."""
    return _latest_action(_entries(log_content))


def _entries(log_content: str) -> Iterator[dict[str, Any]]:
    for line in log_content.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            yield entry


def _latest_action(entries: Iterable[dict[str, Any]]) -> AgentAction | None:
    calls: dict[str, _ToolCall] = {}
    latest: str | None = None
    first_activity_at: dt.datetime | None = None
    last_activity_at: dt.datetime | None = None
    for entry in entries:
        update = _session_update(entry)
        timestamp = _timestamp(entry)
        if update is None or timestamp is None:
            continue
        first_activity_at = first_activity_at or timestamp
        last_activity_at = timestamp
        if update.get("sessionUpdate") not in ("tool_call", "tool_call_update"):
            continue
        call_id = update.get("toolCallId")
        if not isinstance(call_id, str):
            continue
        call = calls.get(call_id)
        name = _tool_name(update) or (call.name if call else "")
        tool_kind = update.get("kind") if isinstance(update.get("kind"), str) else (call.tool_kind if call else None)
        raw_input = update.get("rawInput") if isinstance(update.get("rawInput"), dict) else {}
        if call is None:
            kind, subject, panel_count = _describe(name, tool_kind, raw_input)
            call = calls[call_id] = _ToolCall(
                started_at=timestamp,
                name=name,
                tool_kind=tool_kind,
                kind=kind,
                subject=subject,
                panel_count=panel_count,
            )
            latest = call_id
        elif raw_input:
            # Claude streams a call with an empty input first, so a later update carries the tool's arguments.
            call.name, call.tool_kind = name, tool_kind
            call.kind, call.subject, call.panel_count = _describe(name, tool_kind, raw_input)
        if update.get("status") in _TERMINAL_STATUSES and call.ended_at is None:
            call.ended_at = timestamp
    if first_activity_at is None or last_activity_at is None:
        return None
    current = calls.get(latest) if latest else None
    if current is None:
        return AgentAction(
            kind=AgentActivityKind.THINKING, started_at=first_activity_at, last_activity_at=last_activity_at
        )
    if current.ended_at is not None:
        return AgentAction(
            kind=AgentActivityKind.THINKING, started_at=current.ended_at, last_activity_at=last_activity_at
        )
    return AgentAction(
        kind=current.kind,
        started_at=current.started_at,
        last_activity_at=last_activity_at,
        subject=current.subject,
        panel_count=current.panel_count,
    )


def _session_update(entry: dict[str, Any]) -> dict[str, Any] | None:
    notification = entry.get("notification") if entry.get("type") == "notification" else None
    if not isinstance(notification, dict) or notification.get("method") != "session/update":
        return None
    update = (notification.get("params") or {}).get("update")
    return update if isinstance(update, dict) else None


def _timestamp(entry: dict[str, Any]) -> dt.datetime | None:
    raw = entry.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _tool_name(update: dict[str, Any]) -> str:
    meta = update.get("_meta") if isinstance(update.get("_meta"), dict) else {}
    name = (meta.get("posthog") or {}).get("toolName") or (meta.get("claudeCode") or {}).get("toolName")
    return name if isinstance(name, str) else ""


def _describe(
    name: str, tool_kind: str | None, raw_input: dict[str, Any]
) -> tuple[AgentActivityKind, str | None, int | None]:
    lowered = name.lower()
    if lowered.startswith(_POSTHOG_MCP_PREFIX):
        tool, args = lowered.removeprefix(_POSTHOG_MCP_PREFIX), raw_input
        if tool == "exec":
            tool, args = _exec_call(raw_input.get("command"))
        kind = _TOOL_KINDS.get(tool, AgentActivityKind.WORKING)
        return kind, _subject(kind, args), _panel_count(kind, args)
    if lowered in _LOCAL_TOOLS or (not lowered and tool_kind in _LOCAL_KINDS):
        # The sandbox holds only the import inputs, so a local read or command reads the dashboard.
        return AgentActivityKind.READING_DASHBOARD, None, None
    return AgentActivityKind.WORKING, None, None


def _exec_call(command: object) -> tuple[str, dict[str, Any]]:
    match = _EXEC_CALL.match(command) if isinstance(command, str) else None
    if match is None:
        return "", {}
    try:
        args = json.loads(match["args"]) if match["args"].strip() else {}
    except json.JSONDecodeError:
        args = {}
    return match["tool"].lower(), args if isinstance(args, dict) else {}


def _subject(kind: AgentActivityKind, args: dict[str, Any]) -> str | None:
    field = {
        AgentActivityKind.SEARCHING_METRICS: "value",
        AgentActivityKind.READING_LABELS: "metricName",
        AgentActivityKind.READING_LABEL_VALUES: "key",
    }.get(kind)
    value = args.get(field) if field else None
    return value[:_MAX_SUBJECT_LENGTH] if isinstance(value, str) and value.strip() else None


def _panel_count(kind: AgentActivityKind, args: dict[str, Any]) -> int | None:
    panels = args.get("panels") if kind == AgentActivityKind.CHECKING_PANELS else None
    return len(panels) if isinstance(panels, list) else None
