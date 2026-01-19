from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot, Task
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import (
    GitHubAuthenticationError,
    OAuthTokenError,
    SnapshotNotFoundError,
    SnapshotNotReadyError,
    TaskNotFoundError,
)
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_github_token, get_sandbox_name_for_task

from .get_task_processing_context import TaskProcessingContext


@dataclass
class CreateSandboxFromSnapshotInput:
    context: TaskProcessingContext
    snapshot_id: str


@dataclass
class CreateSandboxFromSnapshotOutput:
    sandbox_id: str


@activity.defn
@asyncify
def create_sandbox_from_snapshot(input: CreateSandboxFromSnapshotInput) -> CreateSandboxFromSnapshotOutput:
    """Create a sandbox from a snapshot for task execution with injected environment variables."""
    ctx = input.context

    with log_activity_execution(
        "create_sandbox_from_snapshot",
        snapshot_id=input.snapshot_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", "Creating development environment from snapshot")

        try:
            snapshot = SandboxSnapshot.objects.get(id=input.snapshot_id)
        except SandboxSnapshot.DoesNotExist as e:
            raise SnapshotNotFoundError(
                f"Snapshot {input.snapshot_id} not found", {"snapshot_id": input.snapshot_id}, cause=e
            )

        if snapshot.status != SandboxSnapshot.Status.COMPLETE:
            raise SnapshotNotReadyError(
                f"Snapshot {input.snapshot_id} is not ready (status: {snapshot.status})",
                {"snapshot_id": input.snapshot_id, "status": snapshot.status},
                cause=RuntimeError(f"Snapshot status is {snapshot.status}, expected COMPLETE"),
            )

        try:
            task = Task.objects.select_related("created_by").get(id=ctx.task_id)
        except Task.DoesNotExist as e:
            raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)

        try:
            github_token = get_github_token(ctx.github_integration_id) or ""
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {ctx.github_integration_id}",
                {
                    "github_integration_id": ctx.github_integration_id,
                    "task_id": ctx.task_id,
                    "team_id": ctx.team_id,
                    "error": str(e),
                },
                cause=e,
            )

        try:
            access_token = create_oauth_access_token(task)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "team_id": ctx.team_id, "error": str(e)},
                cause=e,
            )

        environment_variables = {
            "GITHUB_TOKEN": github_token,
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_API_URL": settings.SITE_URL,
            "POSTHOG_PROJECT_ID": str(ctx.team_id),
        }

        config = SandboxConfig(
            name=get_sandbox_name_for_task(ctx.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=environment_variables,
            snapshot_id=str(snapshot.id),
            metadata={"task_id": ctx.task_id},
        )

        sandbox = Sandbox.create(config)

        activity.logger.info(f"Created sandbox {sandbox.id} with environment variables injected")

        return CreateSandboxFromSnapshotOutput(sandbox_id=sandbox.id)
