from dataclasses import dataclass

from temporalio import activity

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.scopes import API_SCOPE_OBJECTS
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment


@dataclass
class InjectPersonalAPIKeyInput:
    sandbox_id: str
    task_id: str


@dataclass
class InjectPersonalAPIKeyOutput:
    personal_api_key_id: str


@asyncify
def _get_task(task_id: str) -> Task:
    return Task.objects.select_related("created_by").get(id=task_id)


@asyncify
def _create_personal_api_key(task: Task) -> PersonalAPIKey:
    scopes = _get_default_scopes()

    value = generate_random_token_personal()

    mask_value = mask_key_value(value)
    secure_value = hash_key_value(value)

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
    task = await _get_task(input.task_id)

    if not task.created_by:
        raise RuntimeError(f"Task {input.task_id} has no created_by user")

    value, personal_api_key = await _create_personal_api_key(task)

    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

    result = await sandbox.execute(
        f"echo 'export POSTHOG_PERSONAL_API_KEY=\"{value}\"' >> ~/.bash_profile && echo 'export POSTHOG_PERSONAL_API_KEY=\"{value}\"' >> ~/.bashrc"
    )

    if result.exit_code != 0:
        raise RuntimeError(f"Failed to inject personal API key into sandbox environment.")

    return InjectPersonalAPIKeyOutput(personal_api_key_id=personal_api_key.id)


def _get_default_scopes() -> list[str]:
    """
    Get default scopes for task agent API keys.

    TODO: Make scopes configurable per task in the future.
    For now, we provide read access to most resources.
    """
    read_scopes = [f"{obj}:read" for obj in API_SCOPE_OBJECTS if obj not in ["INTERNAL"]]

    return read_scopes
