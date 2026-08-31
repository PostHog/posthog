"""Narrow test-fixture surface for consumers of the tasks facade."""

from uuid import UUID

from products.tasks.backend.models import Task, TaskRun, TaskStagedRunTransition
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run


def create_staged_run_transition_for_test(
    *,
    team_id: int,
    caller_id: UUID,
    task: Task,
    source_task_run: TaskRun,
    successor_task_run: TaskRun,
    source_workspace_snapshot_ref: str,
    requested_capability_manifest: dict[str, object],
    idempotency_key: str,
) -> UUID:
    transition = TaskStagedRunTransition.objects.for_team(team_id).create(
        team_id=team_id,
        caller_id=caller_id,
        task=task,
        source_task_run=source_task_run,
        successor_task_run=successor_task_run,
        source_workspace_snapshot_ref=source_workspace_snapshot_ref,
        requested_capability_manifest=requested_capability_manifest,
        status=TaskStagedRunTransition.Status.ADVANCED,
        idempotency_key=idempotency_key,
    )
    return transition.id


def create_oauth_access_token_for_run_for_test(task: Task, state: dict[str, object] | None) -> str:
    return create_oauth_access_token_for_run(task, state)


__all__ = ["create_oauth_access_token_for_run_for_test", "create_staged_run_transition_for_test"]
