from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from temporalio import activity

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.temporal.common.utils import asyncify
from posthog.utils import get_instance_region

from products.tasks.backend.models import SandboxSnapshot, Task
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import (
    GitHubAuthenticationError,
    OAuthTokenError,
    TaskInvalidStateError,
    TaskNotFoundError,
)
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_github_token, get_sandbox_name_for_task

from .get_task_processing_context import TaskProcessingContext

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"


@dataclass
class GetSandboxForSetupInput:
    context: TaskProcessingContext


@dataclass
class GetSandboxForSetupOutput:
    sandbox_id: str


def _get_array_app() -> OAuthApplication:
    """Get the Array app OAuth application based on the deployment region."""
    region = get_instance_region()
    if region == "EU":
        client_id = ARRAY_APP_CLIENT_ID_EU
    elif region in ("DEV", "E2E"):
        client_id = ARRAY_APP_CLIENT_ID_DEV
    else:
        client_id = ARRAY_APP_CLIENT_ID_US

    try:
        return OAuthApplication.objects.get(client_id=client_id)
    except OAuthApplication.DoesNotExist:
        raise OAuthTokenError(
            f"Array app not found for region {region}",
            {"region": region, "client_id": client_id},
            cause=RuntimeError(f"No OAuthApplication with client_id={client_id}"),
        )


def _create_oauth_access_token(task: Task) -> str:
    """Create an OAuth access token for the Array app, scoped to the task's team.

    OAuth tokens auto-expire after 1 hour, so no cleanup is needed.
    """
    scopes = _get_default_scopes()

    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    app = _get_array_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=task.created_by,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(hours=1),
        scope=" ".join(scopes),
        scoped_teams=[task.team_id],
    )

    return token_value


def _get_default_scopes() -> list[str]:
    return [
        "error_tracking:read",
        "user:read",
        "organization:read",
        "project:read",
        "task:write",
    ]


@activity.defn
@asyncify
def get_sandbox_for_setup(input: GetSandboxForSetupInput) -> GetSandboxForSetupOutput:
    """
    Get sandbox for setup with injected environment variables. Searches for existing snapshot to use as base,
    otherwise uses default template. Returns sandbox_id when sandbox is running.
    """
    ctx = input.context

    with log_activity_execution(
        "get_sandbox_for_setup",
        **ctx.to_log_context(),
    ):
        snapshot = SandboxSnapshot.get_latest_snapshot_for_integration(ctx.github_integration_id)

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
                    "error": str(e),
                },
                cause=e,
            )

        try:
            access_token = _create_oauth_access_token(task)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
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
            snapshot_id=str(snapshot.id) if snapshot else None,
            metadata={"task_id": ctx.task_id},
        )

        sandbox = Sandbox.create(config)

        activity.logger.info(f"Created setup sandbox {sandbox.id} with environment variables injected")

        return GetSandboxForSetupOutput(sandbox_id=sandbox.id)
