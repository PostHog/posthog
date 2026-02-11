import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot, Task, TaskRun
from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, OAuthTokenError, TaskNotFoundError
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import (
    get_github_token,
    get_sandbox_api_url,
    get_sandbox_name_for_task,
)

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)


@dataclass
class GetSandboxForRepositoryInput:
    context: TaskProcessingContext


@dataclass
class GetSandboxForRepositoryOutput:
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None
    used_snapshot: bool
    should_create_snapshot: bool


@activity.defn
@asyncify
def get_sandbox_for_repository(input: GetSandboxForRepositoryInput) -> GetSandboxForRepositoryOutput:
    ctx = input.context

    with log_activity_execution(
        "get_sandbox_for_repository",
        **ctx.to_log_context(),
    ):
        snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(ctx.github_integration_id, [ctx.repository])
        used_snapshot = snapshot is not None

        if used_snapshot:
            emit_agent_log(ctx.run_id, "info", f"Found existing environment for {ctx.repository}")
        else:
            emit_agent_log(ctx.run_id, "debug", f"Creating environment from base image for {ctx.repository}")

        try:
            task = Task.objects.select_related("created_by").get(id=ctx.task_id)
        except Task.DoesNotExist as e:
            raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)

        try:
            github_token = get_github_token(ctx.github_integration_id) or ""
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {ctx.github_integration_id}",
                {"github_integration_id": ctx.github_integration_id, "task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        try:
            access_token = create_oauth_access_token(task)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        environment_variables = {
            "GITHUB_TOKEN": github_token,
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_API_URL": get_sandbox_api_url(),
            "POSTHOG_PROJECT_ID": str(ctx.team_id),
            "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
        }

        config = SandboxConfig(
            name=get_sandbox_name_for_task(ctx.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=environment_variables,
            snapshot_id=str(snapshot.id) if snapshot else None,
            metadata={"task_id": ctx.task_id},
        )

        sandbox = Sandbox.create(config)

        if not used_snapshot:
            emit_agent_log(ctx.run_id, "info", f"Cloning {ctx.repository} into sandbox")
            clone_result = sandbox.clone_repository(ctx.repository, github_token=github_token)
            if clone_result.exit_code != 0:
                sandbox.destroy()
                raise RuntimeError(f"Failed to clone repository {ctx.repository}: {clone_result.stderr}")

        credentials = sandbox.get_connect_credentials()

        task_run = TaskRun.objects.get(id=ctx.run_id)
        state = task_run.state or {}
        state["sandbox_id"] = sandbox.id
        state["sandbox_url"] = credentials.url
        if credentials.token:
            state["sandbox_connect_token"] = credentials.token
        task_run.state = state
        task_run.save(update_fields=["state", "updated_at"])

        activity.logger.info(f"Created sandbox {sandbox.id} (used_snapshot={used_snapshot})")

        return GetSandboxForRepositoryOutput(
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
        )
