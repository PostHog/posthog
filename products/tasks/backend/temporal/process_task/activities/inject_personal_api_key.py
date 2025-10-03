from dataclasses import dataclass

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.scopes import API_SCOPE_OBJECTS

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment


@dataclass
class InjectPersonalAPIKeyInput:
    sandbox_id: str
    task_id: str


@dataclass
class InjectPersonalAPIKeyOutput:
    personal_api_key_id: str


@activity.defn
async def inject_personal_api_key(input: InjectPersonalAPIKeyInput) -> InjectPersonalAPIKeyOutput:
    task = await sync_to_async(Task.objects.select_related("created_by").get)(id=input.task_id)

    if not task.created_by:
        raise RuntimeError(f"Task {input.task_id} has no created_by user")

    scopes = _get_default_scopes()

    value = generate_random_token_personal()

    mask_value = mask_key_value(value)
    secure_value = hash_key_value(value)

    personal_api_key = await sync_to_async(PersonalAPIKey.objects.create)(
        user=task.created_by,
        label=f"Temporary API key for task agent (Task ID: {task.id})",
        secure_value=secure_value,
        mask_value=mask_value,
        scopes=scopes,
        scoped_teams=[task.team_id],
    )

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
