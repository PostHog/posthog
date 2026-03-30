from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.observability import emit_agent_log, log_with_activity_context


@dataclass
class GetTaskProcessingContextInput:
    run_id: str
    create_pr: bool = True


@dataclass
class TaskProcessingContext:
    """
    Serializable context object passed to all activities in the task processing workflow.
    Contains all the information needed to execute activities and emit logs.
    """

    task_id: str
    run_id: str
    team_id: int
    github_integration_id: int | None
    repository: str | None
    distinct_id: str
    create_pr: bool = True
    state: dict | None = None
    _branch: str | None = None

    @property
    def mode(self) -> str:
        """Get the execution mode from state. Defaults to 'background'."""
        return (self.state or {}).get("mode", "background")

    @property
    def interaction_origin(self) -> str | None:
        return (self.state or {}).get("interaction_origin")

    @property
    def sandbox_environment_id(self) -> str | None:
        return (self.state or {}).get("sandbox_environment_id")

    def get_sandbox_environment(self):
        """Resolve the SandboxEnvironment, team-scoped via the TaskRun model."""
        from products.tasks.backend.models import TaskRun

        try:
            task_run = TaskRun.objects.select_related("task").get(id=self.run_id)
            return task_run.get_sandbox_environment()
        except TaskRun.DoesNotExist:
            return None

    @property
    def branch(self) -> str | None:
        # Prefer the dedicated model field; fall back to state for backward compatibility
        if self._branch:
            return self._branch
        value = (self.state or {}).get("branch")
        return value if isinstance(value, str) else None

    def to_log_context(self) -> dict:
        """Return a dict suitable for structured logging."""
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "team_id": self.team_id,
            "repository": self.repository,
            "distinct_id": self.distinct_id,
            "mode": self.mode,
        }


@activity.defn
@asyncify
def get_task_processing_context(input: GetTaskProcessingContextInput) -> TaskProcessingContext:
    """Fetch task details and create the processing context for the workflow."""
    run_id = input.run_id
    log_with_activity_context("Fetching task processing context", run_id=run_id)

    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=run_id)
    except ObjectDoesNotExist as e:
        raise TaskNotFoundError(f"TaskRun {run_id} not found", {"run_id": run_id}, cause=e)

    emit_agent_log(run_id, "info", "Fetching task details")

    task = task_run.task

    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    assert task.created_by is not None

    distinct_id = task.created_by.distinct_id or "process_task_workflow"

    log_with_activity_context(
        "Task processing context created",
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        repository=task.repository,
        distinct_id=distinct_id,
    )

    return TaskProcessingContext(
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        github_integration_id=task.github_integration_id,
        repository=task.repository,
        distinct_id=distinct_id,
        create_pr=input.create_pr,
        state=task_run.state,
        _branch=task_run.branch,
    )
