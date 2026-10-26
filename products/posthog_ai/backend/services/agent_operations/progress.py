"""A compact view of a run's progress, read from its persisted log.

The log is durable, so a client that reconnects after a long gap still gets the latest plan. Step
indexes count from the start of the resume chain, which only grows, so a cursor stays valid
across the runs of one operation.
"""

from collections.abc import Iterable
from typing import Any

from posthog.dataclasses import frozen

from products.slack_app.backend.facade.api import agent_plan_steps, phase_for_tool_call, tool_call_from_acp_update

PERMISSION_REQUEST_METHOD = "_posthog/permission_request"
PERMISSION_RESOLVED_METHOD = "_posthog/permission_resolved"
TERMINAL_TOOL_STATUSES = frozenset({"completed", "failed"})
PLAN_STATUSES = {"complete": "completed", "error": "failed", "in_progress": "in_progress", "pending": "pending"}
MAX_DETAIL_LENGTH = 600


@frozen
class PermissionRequest:
    request_id: str
    tool_call_id: str | None
    title: str
    # The exact PostHog command that waits for approval, so the user sees what runs.
    detail: str | None
    tool_name: str | None
    options: list[dict[str, str]]


@frozen
class RunProgress:
    plan: list[dict[str, str]]
    steps: list[str]
    pending_permission: PermissionRequest | None


def _session_update(entry: dict[str, Any]) -> dict[str, Any] | None:
    notification = entry.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != "session/update":
        return None
    params = notification.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    return update if isinstance(update, dict) else None


def _notification_params(entry: dict[str, Any], method: str) -> dict[str, Any] | None:
    notification = entry.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != method:
        return None
    params = notification.get("params")
    return params if isinstance(params, dict) else None


def _clip(text: str) -> str:
    return text if len(text) <= MAX_DETAIL_LENGTH else text[: MAX_DETAIL_LENGTH - 1] + "…"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tool_name(tool_call: dict[str, Any]) -> str | None:
    # The Claude adapter sets `_meta` only for MCP tools, but it puts the tool name in `rawInput` for every tool.
    meta = _dict(tool_call.get("_meta"))
    names = (
        _dict(meta.get("claudeCode")).get("toolName"),
        _dict(meta.get("posthog")).get("toolName"),
        _dict(tool_call.get("rawInput")).get("toolName"),
    )
    return next((name for name in names if isinstance(name, str) and name), None)


def _label(tool_call: dict[str, Any], tool_name: str | None, raw_title: str) -> tuple[str, str | None]:
    """The step-list label of the tool call that waits for approval, and the PostHog command it runs."""
    step = tool_call_from_acp_update(
        {**tool_call, "_meta": {"claudeCode": {"toolName": tool_name}}} if tool_name else tool_call
    )
    if step is None:
        return raw_title, None
    phase = phase_for_tool_call(step)
    title = (step.description or phase.title) if phase is not None else raw_title
    detail = _clip(step.command) if step.posthog_tool and step.command else None
    return title, detail


def _permission_request(entry: dict[str, Any]) -> PermissionRequest | None:
    params = _notification_params(entry, PERMISSION_REQUEST_METHOD)
    if params is None:
        return None
    request_id = params.get("requestId")
    raw_tool_call = params.get("toolCall")
    tool_call: dict[str, Any] = raw_tool_call if isinstance(raw_tool_call, dict) else {}
    options = [
        {"option_id": option["optionId"], "kind": str(option.get("kind") or ""), "name": str(option.get("name") or "")}
        for option in params.get("options") or []
        if isinstance(option, dict) and isinstance(option.get("optionId"), str)
    ]
    if not isinstance(request_id, str) or not options:
        return None
    raw_title = tool_call.get("title")
    tool_name = _tool_name(tool_call)
    title, detail = _label(tool_call, tool_name, raw_title if isinstance(raw_title, str) else "Run a tool")
    raw_tool_call_id = tool_call.get("toolCallId")
    tool_call_id = raw_tool_call_id if isinstance(raw_tool_call_id, str) else None
    return PermissionRequest(
        request_id=request_id,
        tool_call_id=tool_call_id,
        title=title,
        detail=detail,
        tool_name=tool_name,
        options=options,
    )


def summarize_run_log(entries: Iterable[dict[str, Any]]) -> RunProgress:
    plan: list[dict[str, str]] = []
    steps: list[str] = []
    seen_tool_calls: set[str] = set()
    pending: PermissionRequest | None = None

    for entry in entries:
        request = _permission_request(entry)
        if request is not None:
            pending = request
            continue
        resolved = _notification_params(entry, PERMISSION_RESOLVED_METHOD)
        if resolved is not None:
            if pending is not None and resolved.get("requestId") == pending.request_id:
                pending = None
            continue
        update = _session_update(entry)
        if update is None:
            continue
        plan_steps = agent_plan_steps(update)
        if plan_steps is not None:
            plan = [
                {"content": step["title"], "status": PLAN_STATUSES.get(step["status"], "pending")}
                for step in plan_steps
            ]
            continue
        if update.get("sessionUpdate") not in ("tool_call", "tool_call_update"):
            continue
        tool_call_id = update.get("toolCallId")
        if (
            pending is not None
            and tool_call_id == pending.tool_call_id
            and update.get("status") in TERMINAL_TOOL_STATUSES
        ):
            pending = None
        if not isinstance(tool_call_id, str) or tool_call_id in seen_tool_calls:
            continue
        tool_call = tool_call_from_acp_update(update)
        if tool_call is None:
            continue
        seen_tool_calls.add(tool_call_id)
        phase = phase_for_tool_call(tool_call)
        if phase is not None:
            steps.append(tool_call.description or phase.title)

    return RunProgress(plan=plan, steps=steps, pending_permission=pending)
