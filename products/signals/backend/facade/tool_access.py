"""The per-scout MCP tool policy, as the API enforces it.

A scout owner can pick the exact MCP tools a scout may call. The sandbox holds the run's
OAuth token, so the agent can call the REST API without the MCP server, and the token's
scopes are coarse: `ticket:write` covers a private note and a reply to the customer alike.
The API therefore refuses each operation that no held tool calls.

The policy is read from the task the token is bound to (`OAuthAccessToken.sandbox_task_id`),
which is written server-side at mint time. A header the sandbox sends is never trusted.
Core reads the policy through this module so `posthog.permissions` never imports a signals model.
"""

from __future__ import annotations

from uuid import UUID

from posthog.models.team.team import Team

from products.signals.backend.scout_harness.tool_catalogue import (
    scout_held_operations,
    scout_held_tools,
    scout_tool_access_enabled,
)
from products.tasks.backend.facade import api as tasks_facade


def resolve_scout_held_operations(*, sandbox_task_id: UUID, team_id: int) -> frozenset[str] | None:
    """The operations a scout run may call, or None when no per-tool policy applies.

    None when the task has no stamped tool list, or when the team lacks `scouts-tool-access`.
    """
    allowlist = tasks_facade.get_task_mcp_tool_allowlist(sandbox_task_id, team_id)
    if allowlist is None:
        return None
    team = Team.objects.filter(id=team_id).first()
    if team is None or not scout_tool_access_enabled(team):
        return None
    return scout_held_operations(scout_held_tools(allowlist))
