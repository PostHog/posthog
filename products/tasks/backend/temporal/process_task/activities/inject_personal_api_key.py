import shlex
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.scopes import API_SCOPE_OBJECTS
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
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


@asyncify
def _get_task(task_id: str) -> Task:
    return Task.objects.select_related("created_by").get(id=task_id)


@asyncify
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
async def inject_personal_api_key(input: InjectPersonalAPIKeyInput) -> InjectPersonalAPIKeyOutput:
    async with log_activity_execution(
        "inject_personal_api_key",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
    ):
        try:
            task = await _get_task(input.task_id)
        except ObjectDoesNotExist:
            raise TaskNotFoundError(f"Task {input.task_id} not found", {"task_id": input.task_id})

        if not task.created_by:
            raise TaskInvalidStateError(f"Task {input.task_id} has no created_by user", {"task_id": input.task_id})

        try:
            api_key_tuple: tuple[str, PersonalAPIKey] = await _create_personal_api_key(task)
            value, personal_api_key = api_key_tuple
        except Exception as e:
            raise PersonalAPIKeyError(
                f"Failed to create personal API key for task {input.task_id}",
                {"task_id": input.task_id, "error": str(e)},
            )

        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

        escaped_value = shlex.quote(value)

        result = await sandbox.execute(
            f"echo 'export POSTHOG_PERSONAL_API_KEY={escaped_value}' >> ~/.bash_profile && echo 'export POSTHOG_PERSONAL_API_KEY={escaped_value}' >> ~/.bashrc"
        )

        if result.exit_code != 0:
            raise SandboxExecutionError(
                f"Failed to inject personal API key into sandbox",
                {"sandbox_id": input.sandbox_id, "exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )

        return InjectPersonalAPIKeyOutput(personal_api_key_id=personal_api_key.id)


def _get_default_scopes() -> list[str]:
    """
    Get default scopes for task agent API keys.

    TODO: Make scopes configurable per task in the future.
    For now, we provide read access to most resources.
    """
    read_scopes = [f"{obj}:read" for obj in API_SCOPE_OBJECTS if obj not in ["INTERNAL"]]

    return read_scopes
