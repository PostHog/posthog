"""
Function facade for runs that an agent in a task sandbox starts.

The request layer reads the sandbox credential. This module decides whether the run behind
that credential may start a run, and caps how many runs one parent run may start. Each child run
records its parent in its state, which ``run_task`` writes before the workflow starts.
"""

from uuid import UUID

from products.tasks.backend.facade import contracts
from products.tasks.backend.metrics import observe_sandbox_run_start
from products.tasks.backend.models import Task, TaskRun

__all__ = [
    "AGENT_PARENT_RUN_ID_STATE_KEY",
    "AGENT_PARENT_TASK_ID_STATE_KEY",
    "AGENT_RUN_FANOUT_CAP",
    "AGENT_STARTED_RUN_COUNT_STATE_KEY",
    "capture_sandbox_run_start_refused",
    "observe_sandbox_run_start",
    "release_agent_run_slot",
    "reserve_agent_run_slot",
    "resolve_sandbox_run_starter",
]

AGENT_RUN_FANOUT_CAP = 10
AGENT_PARENT_TASK_ID_STATE_KEY = "agent_parent_task_id"
AGENT_PARENT_RUN_ID_STATE_KEY = "agent_parent_run_id"
AGENT_STARTED_RUN_COUNT_STATE_KEY = "agent_started_run_count"


def _as_uuid(value: str | UUID | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def resolve_sandbox_run_starter(
    team_id: int,
    *,
    sandbox_task_id: UUID | None,
    token_id: int | None,
    user_id: int | None,
    target_task_id: str | UUID | None = None,
) -> contracts.SandboxRunStarter | contracts.SandboxRunStartDenial:
    """Resolve the run whose sandbox sent the request, and check that it may start a run.

    The credential user must be the person who created the run's task, so every gate the caller
    applies next runs as that person. A run that a sandbox started cannot start more runs.
    """
    if sandbox_task_id is None or user_id is None or token_id is None:
        return contracts.SandboxRunStartDenial.NO_ACTOR
    if not Task.objects.filter(id=sandbox_task_id, team_id=team_id, deleted=False, created_by_id=user_id).exists():
        return contracts.SandboxRunStartDenial.NO_ACTOR
    bound_run = (
        TaskRun.objects.filter(
            task_id=sandbox_task_id,
            team_id=team_id,
            state__sandbox_oauth_token_ids__contains=[str(token_id)],
        )
        .only("id", "state")
        .first()
    )
    if bound_run is None:
        return contracts.SandboxRunStartDenial.NO_ACTOR
    # The bound run decides, not other runs of the task, so a person can still resume a task that
    # once ran as a child. `run_task` carries the parent keys across a resume of a child run.
    if _as_uuid(target_task_id) == sandbox_task_id or AGENT_PARENT_TASK_ID_STATE_KEY in (bound_run.state or {}):
        return contracts.SandboxRunStartDenial.NESTED
    return contracts.SandboxRunStarter(parent_task_id=sandbox_task_id, parent_run_id=bound_run.id)


def reserve_agent_run_slot(parent_run_id: UUID) -> bool:
    """Count one more run against the parent run's cap. Returns False when the cap is full.

    The count lives on the parent run, so each new run of the parent task starts with a full cap.
    """
    reserved = False

    def _reserve(state: dict) -> None:
        nonlocal reserved
        count = state.get(AGENT_STARTED_RUN_COUNT_STATE_KEY, 0)
        if count >= AGENT_RUN_FANOUT_CAP:
            return
        state[AGENT_STARTED_RUN_COUNT_STATE_KEY] = count + 1
        reserved = True

    TaskRun.mutate_state_atomic(parent_run_id, _reserve)
    return reserved


def release_agent_run_slot(parent_run_id: UUID) -> None:
    """Give back a slot that ``reserve_agent_run_slot`` took for a run that did not start."""

    def _release(state: dict) -> None:
        count = state.get(AGENT_STARTED_RUN_COUNT_STATE_KEY, 0)
        if count > 0:
            state[AGENT_STARTED_RUN_COUNT_STATE_KEY] = count - 1

    TaskRun.mutate_state_atomic(parent_run_id, _release)


def capture_sandbox_run_start_refused(
    team_id: int, *, sandbox_task_id: UUID | None, reason: str, endpoint: str
) -> None:
    """Record that a task sandbox asked to start a run and was refused, on the sandbox's own task.

    A refusal without a task behind the credential has no task to attach to, so it is not recorded.
    """
    if sandbox_task_id is None:
        return
    task = Task.objects.filter(id=sandbox_task_id, team_id=team_id).select_related("created_by", "team").first()
    if task is not None:
        task.capture_event("task_run_agent_start_refused", {"reason": reason, "endpoint": endpoint})
