"""The MCP Store hook that limits a run token to the connections its run snapshotted. Loads on django.setup(), so it
keeps the Temporal utilities off the import path."""

from typing import Any
from uuid import UUID

from products.mcp_store.backend.facade.run_scope_hooks import register_run_installation_allowlist
from products.tasks.backend.models import TaskRun


def mcp_installation_allowlist_for_token(task_id: UUID | str, token_id: str) -> list[str] | None:
    """The MCP Store installations the run that owns a sandbox token snapshotted at dispatch, or None when it has no
    snapshot. Each run records the ids of the tokens minted for it, so the token resolves to exactly one run.

    A snapshot that is present but malformed allows nothing. So does a token bound to no run of a task whose runs
    carry snapshots, because the run it came from cannot be told apart.
    """
    snapshots = list(
        TaskRun.objects.filter(task_id=task_id, state__sandbox_oauth_token_ids__contains=[token_id]).values_list(
            "state__config_snapshot", flat=True
        )[:1]
    )
    if not snapshots:
        return [] if TaskRun.objects.filter(task_id=task_id, state__has_key="config_snapshot").exists() else None
    return _installation_ids(snapshots[0])


def _installation_ids(snapshot: Any) -> list[str] | None:
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the setup path
        loop_mcp_installation_allowlist,
    )

    if snapshot is None:
        return None
    if not isinstance(snapshot, dict):
        return []
    return loop_mcp_installation_allowlist({"config_snapshot": snapshot})


def register() -> None:
    register_run_installation_allowlist(mcp_installation_allowlist_for_token)
