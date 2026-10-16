"""
Function facade for runs that an agent in a task sandbox starts.

The request layer reads the sandbox credential. This module decides whether the task behind
that credential may start a run, caps how many runs one task may start, and links each child
task to the task that started it.
"""

from uuid import UUID

from products.tasks.backend.facade import contracts
from products.tasks.backend.models import Task, TaskRun

__all__ = [
    "AGENT_PARENT_RUN_ID_STATE_KEY",
    "AGENT_PARENT_TASK_ID_STATE_KEY",
    "AGENT_RUN_FANOUT_CAP",
    "link_agent_started_task",
    "reserve_agent_run_slot",
    "resolve_sandbox_run_starter",
]

AGENT_RUN_FANOUT_CAP = 10
AGENT_PARENT_TASK_ID_STATE_KEY = "agent_parent_task_id"
AGENT_PARENT_RUN_ID_STATE_KEY = "agent_parent_run_id"
_AGENT_STARTED_RUN_COUNT_STATE_KEY = "agent_started_run_count"


def resolve_sandbox_run_starter(
    team_id: int,
    *,
    sandbox_task_id: UUID | None,
    token_id: int | None,
    user_id: int | None,
    target_task_id: str | UUID | None = None,
) -> contracts.SandboxRunStarter | contracts.SandboxRunStartDenial:
    """Resolve the task whose sandbox sent the request, and check that it may start a run.

    The credential user must be the person who created that task, so every gate the caller
    applies next runs as that person. A task that a sandbox started cannot start more runs.
    """
    if sandbox_task_id is None or user_id is None:
        return contracts.SandboxRunStartDenial.NO_ACTOR
    parent = (
        Task.objects.filter(id=sandbox_task_id, team_id=team_id, deleted=False).values("created_by_id", "state").first()
    )
    if parent is None or parent["created_by_id"] is None or parent["created_by_id"] != user_id:
        return contracts.SandboxRunStartDenial.NO_ACTOR
    if (parent["state"] or {}).get(AGENT_PARENT_TASK_ID_STATE_KEY) or (
        target_task_id is not None and str(target_task_id) == str(sandbox_task_id)
    ):
        return contracts.SandboxRunStartDenial.NESTED
    parent_run_id = None
    if token_id is not None:
        parent_run_id = (
            TaskRun.objects.filter(
                task_id=sandbox_task_id,
                team_id=team_id,
                state__sandbox_oauth_token_ids__contains=[str(token_id)],
            )
            .values_list("id", flat=True)
            .first()
        )
    return contracts.SandboxRunStarter(parent_task_id=sandbox_task_id, parent_run_id=parent_run_id)


def reserve_agent_run_slot(team_id: int, parent_task_id: UUID) -> bool:
    """Count one more run against the parent task's cap. Returns False when the cap is full.

    A slot stays spent when the run fails to start, so a retry loop cannot exceed the cap.
    """
    reserved = False

    def _reserve(state: dict) -> None:
        nonlocal reserved
        count = state.get(_AGENT_STARTED_RUN_COUNT_STATE_KEY, 0)
        if count >= AGENT_RUN_FANOUT_CAP:
            return
        state[_AGENT_STARTED_RUN_COUNT_STATE_KEY] = count + 1
        reserved = True

    Task.mutate_state_atomic(parent_task_id, _reserve, team_id=team_id)
    return reserved


def link_agent_started_task(team_id: int, task_id: str | UUID, starter: contracts.SandboxRunStarter) -> None:
    """Record the parent on the child task, which also stops the child's sandbox from starting runs."""

    def _link(state: dict) -> None:
        state[AGENT_PARENT_TASK_ID_STATE_KEY] = str(starter.parent_task_id)
        if starter.parent_run_id is not None:
            state[AGENT_PARENT_RUN_ID_STATE_KEY] = str(starter.parent_run_id)

    Task.mutate_state_atomic(task_id, _link, team_id=team_id)
