from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

import posthoganalytics
from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxEnvironment, Task, TaskRun
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.observability import emit_agent_log, log_with_activity_context
from products.tasks.backend.temporal.process_task.utils import format_allowed_domains_for_log


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
    team_uuid: str
    organization_id: str
    github_integration_id: int | None
    repository: str | None
    distinct_id: str
    create_pr: bool = True
    pr_loop_enabled: bool = False
    state: dict | None = None
    _branch: str | None = None
    sandbox_environment_name: str | None = None
    allowed_domains: list[str] | None = None
    json_schema: dict | None = None
    ci_prompt: str | None = None

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

    @property
    def runtime_adapter(self) -> str | None:
        value = (self.state or {}).get("runtime_adapter")
        return value if isinstance(value, str) else None

    @property
    def provider(self) -> str | None:
        value = (self.state or {}).get("provider")
        return value if isinstance(value, str) else None

    @property
    def model(self) -> str | None:
        value = (self.state or {}).get("model")
        return value if isinstance(value, str) else None

    @property
    def reasoning_effort(self) -> str | None:
        value = (self.state or {}).get("reasoning_effort")
        return value if isinstance(value, str) else None

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
            "sandbox_environment_id": self.sandbox_environment_id,
            "runtime_adapter": self.runtime_adapter,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }


@activity.defn
@asyncify
def get_task_processing_context(input: GetTaskProcessingContextInput) -> TaskProcessingContext:
    """Fetch task details and create the processing context for the workflow."""
    run_id = input.run_id
    log_with_activity_context("Fetching task processing context", run_id=run_id)

    try:
        task_run = TaskRun.objects.select_related("task__created_by", "task__team").get(id=run_id)
    except ObjectDoesNotExist as e:
        raise TaskNotFoundError(f"TaskRun {run_id} not found", {"run_id": run_id}, cause=e)

    emit_agent_log(run_id, "info", "Fetching task details")

    task: Task = task_run.task
    team: Team = task.team
    organization_id = str(team.organization_id)
    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    assert task.created_by is not None

    distinct_id = task.created_by.distinct_id or "process_task_workflow"
    state = task_run.state or {}
    sandbox_environment_id = state.get("sandbox_environment_id")
    sandbox_environment_name: str | None = None
    allowed_domains: list[str] | None = None

    if sandbox_environment_id:
        sandbox_environment = SandboxEnvironment.objects.filter(id=sandbox_environment_id, team=task.team).first()
        if sandbox_environment is None:
            raise TaskInvalidStateError(
                f"Sandbox environment {sandbox_environment_id} not found for team {task.team_id}",
                {"sandbox_environment_id": sandbox_environment_id, "team_id": task.team_id},
                cause=RuntimeError(f"Sandbox environment {sandbox_environment_id} does not exist"),
            )
        else:
            sandbox_environment_name = sandbox_environment.name
            effective_domains = sandbox_environment.get_effective_domains()
            allowed_domains = effective_domains or None

            if allowed_domains:
                emit_agent_log(
                    run_id,
                    "debug",
                    f"Resolved sandbox environment '{sandbox_environment.name}' with agentsh allowlist: {format_allowed_domains_for_log(allowed_domains)}",
                )
            else:
                emit_agent_log(
                    run_id,
                    "debug",
                    f"Resolved sandbox environment '{sandbox_environment.name}' with full network access",
                )

    log_with_activity_context(
        "Task processing context created",
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        repository=task.repository,
        distinct_id=distinct_id,
        sandbox_environment_id=sandbox_environment_id,
    )
    pr_loop_enabled = (
        posthoganalytics.feature_enabled(
            "tasks-pr-loop",
            distinct_id=distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
        )
        or False
    )  # Ensure we get a boolean value even if the flag is missing
    emit_agent_log(run_id, "info", f"pr_loop_enabled: {pr_loop_enabled} for this task run")
    return TaskProcessingContext(
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        team_uuid=str(task.team.uuid),
        organization_id=str(task.team.organization_id),
        github_integration_id=task.github_integration_id,
        repository=task.repository,
        distinct_id=distinct_id,
        create_pr=input.create_pr,
        pr_loop_enabled=pr_loop_enabled,
        state=state,
        _branch=task_run.branch,
        sandbox_environment_name=sandbox_environment_name,
        allowed_domains=allowed_domains,
        json_schema=task.json_schema,
        ci_prompt=task.ci_prompt,
    )
