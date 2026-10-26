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
TERMINAL_TOOL_STATUSES = frozenset({"completed", "failed"})
PLAN_STATUSES = {"complete": "completed", "error": "failed", "in_progress": "in_progress", "pending": "pending"}


@frozen
class PermissionRequest:
    request_id: str
    tool_call_id: str | None
    title: str
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


def _permission_request(entry: dict[str, Any]) -> PermissionRequest | None:
    notification = entry.get("notification")
    if not isinstance(notification, dict) or notification.get("method") != PERMISSION_REQUEST_METHOD:
        return None
    params = notification.get("params")
    if not isinstance(params, dict):
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
    title = raw_title if isinstance(raw_title, str) else "Run a tool"
    raw_tool_call_id = tool_call.get("toolCallId")
    tool_call_id = raw_tool_call_id if isinstance(raw_tool_call_id, str) else None
    return PermissionRequest(request_id=request_id, tool_call_id=tool_call_id, title=title, options=options)


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
