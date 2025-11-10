from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot, Task
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import (
    GitHubAuthenticationError,
    PersonalAPIKeyError,
    SnapshotNotFoundError,
    SnapshotNotReadyError,
    TaskInvalidStateError,
    TaskNotFoundError,
)
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_github_token, get_sandbox_name_for_task


@dataclass
class CreateSandboxFromSnapshotInput:
    snapshot_id: str
    task_id: str
    distinct_id: str
    team_id: int
    github_integration_id: int


def _create_personal_api_key(task: Task) -> tuple[str, PersonalAPIKey]:
    scopes = _get_default_scopes()

    value = generate_random_token_personal()

    mask_value = mask_key_value(value)
    secure_value = hash_key_value(value)

    if not task.created_by:
        raise TaskInvalidStateError(f"Task {task.id} has no created_by user", {"task_id": task.id})

    assert task.created_by is not None

    personal_api_key = PersonalAPIKey.objects.create(
        user=task.created_by,
        label=f"Task Agent - {task.title[:20]}",
        secure_value=secure_value,
        mask_value=mask_value,
        scopes=scopes,
        scoped_teams=[task.team_id],
    )

    return value, personal_api_key


def _get_default_scopes() -> list[str]:
    scopes = [
        "error_tracking:read",
        "user:read",
        "organization:read",
        "project:read",
        "task:write",
    ]

    return scopes


@dataclass
class CreateSandboxFromSnapshotOutput:
    sandbox_id: str
    personal_api_key_id: str


@activity.defn
@asyncify
def create_sandbox_from_snapshot(input: CreateSandboxFromSnapshotInput) -> CreateSandboxFromSnapshotOutput:
    """Create a sandbox from a snapshot for task execution with injected environment variables."""

    with log_activity_execution(
        "create_sandbox_from_snapshot",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        snapshot_id=input.snapshot_id,
        github_integration_id=input.github_integration_id,
    ):
        try:
            snapshot = SandboxSnapshot.objects.get(id=input.snapshot_id)
        except SandboxSnapshot.DoesNotExist:
            raise SnapshotNotFoundError(f"Snapshot {input.snapshot_id} not found", {"snapshot_id": input.snapshot_id})

        if snapshot.status != SandboxSnapshot.Status.COMPLETE:
            raise SnapshotNotReadyError(
                f"Snapshot {input.snapshot_id} is not ready (status: {snapshot.status})",
                {"snapshot_id": input.snapshot_id, "status": snapshot.status},
            )

        try:
            task = Task.objects.select_related("created_by").get(id=input.task_id)
        except Task.DoesNotExist:
            raise TaskNotFoundError(f"Task {input.task_id} not found", {"task_id": input.task_id})

        try:
            github_token = get_github_token(input.github_integration_id) or ""
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {input.github_integration_id}",
                {"github_integration_id": input.github_integration_id, "error": str(e)},
            )

        try:
            api_key_value, personal_api_key = _create_personal_api_key(task)
        except Exception as e:
            raise PersonalAPIKeyError(
                f"Failed to create personal API key for task {input.task_id}",
                {"task_id": input.task_id, "error": str(e)},
            )

        environment_variables = {
            "GITHUB_TOKEN": github_token,
            "POSTHOG_PERSONAL_API_KEY": api_key_value,
            "POSTHOG_API_URL": settings.SITE_URL,
            "POSTHOG_PROJECT_ID": str(input.team_id),
        }

        config = SandboxConfig(
            name=get_sandbox_name_for_task(input.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=environment_variables,
            snapshot_id=str(snapshot.id),
            metadata={"task_id": str(input.task_id)},
        )

        sandbox = Sandbox.create(config)

        activity.logger.info(f"Created sandbox {sandbox.id} with environment variables injected")

        return CreateSandboxFromSnapshotOutput(
            sandbox_id=sandbox.id,
            personal_api_key_id=personal_api_key.id,
        )
