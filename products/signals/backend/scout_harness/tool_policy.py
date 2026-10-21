"""Refuse API writes that a scout run did not pick a tool for.

A scout run's token carries coarse scopes. `ticket:write` lets the token post a note and also a
reply to the customer, and the sandbox holds the token, so the agent can call the REST API
without going through the MCP server. When a scout config narrows the run to a tool list, the
runner stamps the list on the task. This module answers whether one API request belongs to a
tool the run holds. The run comes from the token's task binding, never from a header.

A request is checked when it uses a method other than GET, HEAD, or OPTIONS, or when it needs a
write scope. The method matters because some actions change state behind a read scope. Safe
reads stay governed by the token scopes, so the MCP server and the agent server keep their own
bookkeeping reads.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any
from uuid import UUID

from rest_framework.permissions import SAFE_METHODS

from posthog.mcp_tool_definitions import McpToolApiOperation, get_mcp_tool_definitions
from posthog.mcp_tool_operations import request_matches_operation

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.tool_catalogue import scout_held_mcp_tools
from products.tasks.backend.facade import api as tasks_facade

_RUN = "/api/projects/{project_id}/tasks/{task_id}/runs/{id}/"

# Endpoints the sandbox calls with the run's token outside any PostHog MCP tool, from the agent
# server and harness in `packages/agent/`. A new non-GET endpoint in that code must be added here,
# or a narrowed run gets it refused. The MCP Store's tool calls and tool approvals stay out: they
# reach installations the scout's selection did not mount, and an unattended run must not approve
# tools. `test_scout_tool_policy.py` fails when an entry stops resolving to a view.
SANDBOX_HARNESS_OPERATIONS: tuple[McpToolApiOperation, ...] = tuple(
    McpToolApiOperation(method=method, path=path)
    for method, path in (
        ("GET", "/api/users/@me/"),
        ("GET", "/api/projects/{project_id}/tasks/{id}/"),
        ("GET", _RUN),
        ("PATCH", _RUN),
        ("PATCH", f"{_RUN}set_output/"),
        ("PATCH", f"{_RUN}set_summary/"),
        ("GET", f"{_RUN}task_session/"),
        ("POST", f"{_RUN}task_session_sync/"),
        ("POST", f"{_RUN}subscription_token/"),
        ("POST", f"{_RUN}append_log/"),
        ("GET", f"{_RUN}logs/"),
        ("POST", f"{_RUN}relay_message/"),
        ("POST", f"{_RUN}analysis-activity/"),
        ("POST", f"{_RUN}artifacts/"),
        ("POST", f"{_RUN}artifacts/download/"),
        ("POST", f"{_RUN}artifacts/prepare_upload/"),
        ("POST", f"{_RUN}artifacts/finalize_upload/"),
        ("POST", f"{_RUN}living_artifacts/"),
        ("GET", f"{_RUN}peers/"),
        ("POST", f"{_RUN}peers/{{peer_run_id}}/message/"),
        ("GET", "/api/projects/{project_id}/signals/reports/"),
        ("GET", "/api/projects/{project_id}/mcp_server_installations/{id}/tools/"),
    )
)

TOOL_NOT_GRANTED_CODE = "scout_tool_not_granted"


def resolve_scout_held_tools(*, sandbox_task_id: UUID) -> frozenset[str] | None:
    allowlist = tasks_facade.mcp_tool_allowlist_for_task(sandbox_task_id)
    return scout_held_mcp_tools(allowlist) if allowlist is not None else None


def scout_tool_denial(
    *, sandbox_task_id: UUID, view: Any, method: str, path: str, required_scopes: Iterable[str], data: Any = None
) -> str | None:
    """Why this request is refused, or None when the run may make it.

    Reads the task only for checked requests, and verifies run ownership for run writes.
    """
    if method.upper() in SAFE_METHODS and all(scope.endswith(":read") for scope in required_scopes):
        return None
    held_tools = resolve_scout_held_tools(sandbox_task_id=sandbox_task_id)
    if held_tools is None:
        return None
    for operation in _permitted_operations(held_tools):
        if not request_matches_operation(view=view, method=method, path=path, operation=operation):
            continue
        if operation.path.startswith(_RUN):
            latest = tasks_facade.get_latest_run_by_task([sandbox_task_id]).get(str(sandbox_task_id))
            if (
                str(view.kwargs.get("parent_lookup_task_id")) != str(sandbox_task_id)
                or latest is None
                or str(view.kwargs.get("pk")) != str(latest.id)
            ):
                continue
        if operation.path.startswith("/api/projects/{project_id}/signals/scout/runs/{run_id}/"):
            bound_run_id = (
                SignalScoutRun.objects.for_team(view.team_id)
                .filter(task_run__task_id=sandbox_task_id)
                .order_by("-created_at", "-id")
                .values_list("id", flat=True)
                .first()
            )
            if bound_run_id is None or str(view.kwargs.get("run_id")) != str(bound_run_id):
                continue
        if not _soft_delete_allowed(operation, held_tools, data):
            continue
        return None
    return (
        f"This scout was not given a tool for {method.upper()} {path}. "
        "Its owner picks the tools it can use in the scout settings."
    )


@lru_cache(maxsize=256)
def _permitted_operations(held_tools: frozenset[str]) -> tuple[McpToolApiOperation, ...]:
    definitions = get_mcp_tool_definitions()
    tool_operations = (
        operation
        for name in sorted(held_tools)
        if (definition := definitions.get(name)) is not None
        for operation in definition.api_operations
    )
    return tuple(dict.fromkeys((*SANDBOX_HARNESS_OPERATIONS, *tool_operations)))


@lru_cache(maxsize=1)
def _soft_delete_tools() -> dict[McpToolApiOperation, frozenset[str]]:
    tools: dict[McpToolApiOperation, set[str]] = {}
    for name, definition in get_mcp_tool_definitions().items():
        if name.endswith("-delete") or name in {"delete-feature-flag", "notebooks-destroy"}:
            for operation in definition.api_operations:
                if operation.method == "PATCH":
                    tools.setdefault(operation, set()).add(name)
    return {operation: frozenset(names) for operation, names in tools.items()}


def _soft_delete_allowed(operation: McpToolApiOperation, held_tools: frozenset[str], data: Any) -> bool:
    delete_tools = _soft_delete_tools().get(operation)
    if not delete_tools:
        return True
    definitions = get_mcp_tool_definitions()
    has_update = any(
        name not in delete_tools and operation in definitions[name].api_operations
        for name in held_tools
        if name in definitions
    )
    if isinstance(data, Mapping) and "deleted" in data:
        if not held_tools & delete_tools:
            return False
        return has_update or (set(data) == {"deleted"} and data["deleted"] is True)
    return has_update
