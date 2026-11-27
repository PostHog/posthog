"""The MCP Store hook that limits a run token to the connections its run snapshotted. Loads on django.setup(), so it
keeps the Temporal utilities off the import path."""

from uuid import UUID

from products.mcp_store.backend.facade.run_scope_hooks import register_run_installation_allowlist
from products.tasks.backend.models import TaskRun


def mcp_installation_allowlist_for_task(task_id: UUID | str) -> list[str] | None:
    """The MCP Store installations a task's runs snapshotted at dispatch, or None when no run is narrowed.

    Scoped by task rather than by team, because the caller's authority is a run token minted for exactly this task.
    Once any run carries a snapshot the task stays narrowed, to the union of the snapshots, so a later run without one
    cannot widen it. A malformed snapshot reads as an empty list, so callers fail closed.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the setup path
        loop_mcp_installation_allowlist,
    )

    allowlists = [
        allowlist
        for state in TaskRun.objects.filter(task_id=task_id).values_list("state", flat=True)
        if (allowlist := loop_mcp_installation_allowlist(state)) is not None
    ]
    if not allowlists:
        return None
    return sorted({installation_id for allowlist in allowlists for installation_id in allowlist})


def register() -> None:
    register_run_installation_allowlist(mcp_installation_allowlist_for_task)
