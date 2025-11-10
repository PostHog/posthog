import shlex
from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import (
    PersonalAPIKeyError,
    SandboxExecutionError,
    TaskInvalidStateError,
    TaskNotFoundError,
)
from products.tasks.backend.temporal.observability import log_activity_execution


@dataclass
class InjectPersonalAPIKeyInput:
    sandbox_id: str
    task_id: str
    distinct_id: str


@dataclass
class InjectPersonalAPIKeyOutput:
    personal_api_key_id: str


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


@activity.defn
@asyncify
def inject_personal_api_key(input: InjectPersonalAPIKeyInput) -> InjectPersonalAPIKeyOutput:
    with log_activity_execution(
        "inject_personal_api_key",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
    ):
        try:
            task = Task.objects.select_related("created_by").get(id=input.task_id)
        except Task.DoesNotExist:
            raise TaskNotFoundError(f"Task {input.task_id} not found", {"task_id": input.task_id})

        try:
            api_key_tuple: tuple[str, PersonalAPIKey] = _create_personal_api_key(task)
            value, personal_api_key = api_key_tuple
        except Exception as e:
            raise PersonalAPIKeyError(
                f"Failed to create personal API key for task {input.task_id}",
                {"task_id": input.task_id, "error": str(e)},
            )

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        escaped_value = shlex.quote(value)
        escaped_api_url = shlex.quote(settings.SITE_URL)

        command = (
            f"echo 'export POSTHOG_PERSONAL_API_KEY={escaped_value}' >> ~/.bashrc && "
            f"echo 'export POSTHOG_API_URL={escaped_api_url}' >> ~/.bashrc"
        )

        activity.logger.info(f"Executing command: {command}")
        result = sandbox.execute(command, timeout_seconds=30)
        activity.logger.info(
            f"Command result - exit_code: {result.exit_code}, stdout: {result.stdout}, stderr: {result.stderr}"
        )

        if result.exit_code != 0:
            raise SandboxExecutionError(
                f"Failed to inject personal API key into sandbox",
                {"sandbox_id": input.sandbox_id, "exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )

        verify_result = sandbox.execute("bash -c 'source ~/.bashrc && echo $POSTHOG_PERSONAL_API_KEY'")
        activity.logger.info(
            f"Verification result - exit_code: {verify_result.exit_code}, stdout: {verify_result.stdout}, stderr: {verify_result.stderr}"
        )

        return InjectPersonalAPIKeyOutput(personal_api_key_id=personal_api_key.id)


def _get_default_scopes() -> list[str]:
    # TODO: Make scopes configurable per task in the future.

    scopes = [
        "error_tracking:read",
        "user:read",
        "organization:read",
        "project:read",
        "task:write",
    ]

    return scopes
