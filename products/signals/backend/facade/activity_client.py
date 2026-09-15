"""The activity-log client tag for writes a scout run makes through the MCP.

A scout authenticates with an OAuth token minted on behalf of the person who owns the scout,
so its dashboard, insight and notebook writes name that person in the activity log. The
`x-posthog-client` header the MCP sends is self-reported, and reads `mcp` for a scout run and
for that person's own editor over MCP alike, so the log cannot separate the two. The token
carries the scout's task id, bound server-side at mint time, so the run behind the request is
recoverable here and the tag it produces is trustworthy.
"""

from __future__ import annotations

from uuid import UUID

from products.signals.backend.models import SignalScoutRun

SCOUT_ACTIVITY_CLIENT_PREFIX = "scout:"


def resolve_scout_activity_client(sandbox_task_id: UUID) -> str | None:
    """The `scout:<skill_name>` tag for a sandbox task, or None when no scout ran in it.

    `all_teams`, not `for_team`: authentication runs before any team scope is set, and the
    lookup key is a token field the server wrote, not caller input, so there is no tenant
    choice to make. Ordering matches `run_id_for_sandbox_task`, the sibling resolver off the
    same binding: a retried task holds one run per attempt, and the newest one wins.
    """
    skill_name = (
        SignalScoutRun.all_teams.filter(task_run__task_id=sandbox_task_id)
        .order_by("-created_at", "-id")
        .values_list("skill_name", flat=True)
        .first()
    )
    if not skill_name:
        return None
    return f"{SCOUT_ACTIVITY_CLIENT_PREFIX}{skill_name}"
