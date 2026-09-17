"""The activity-log client tag for the API writes a scout run makes.

A scout authenticates as the person who owns its config, so the acting user on an
activity-log row cannot tell a scout's edit from that person's own MCP edit. The sandbox
OAuth token carries the id of the task the run happens in, and that binding is written
server-side at mint time, which is what makes the tag derived from it trustworthy where the
caller-settable `x-posthog-client` header is not.

Core reads the tag through this module so `posthog.auth` never imports a signals model.
"""

from __future__ import annotations

from uuid import UUID

from products.signals.backend.models import SignalScoutRun

SCOUT_CLIENT_PREFIX = "scout:"


def resolve_scout_client_tag(*, sandbox_task_id: UUID, team_id: int) -> str | None:
    """`scout:<skill_name>` when a scout run owns this task, None when no scout run does.

    A task with several runs (a retry) is still one scout, so any of its rows answers the
    question. The ordering only keeps repeated reads of the same task consistent.
    """
    skill_name = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(task_run__task_id=sandbox_task_id)
        .order_by("-created_at")
        .values_list("skill_name", flat=True)
        .first()
    )
    if not skill_name:
        return None
    return f"{SCOUT_CLIENT_PREFIX}{skill_name}"
