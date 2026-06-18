import json
import asyncio
import logging
from pathlib import Path

from django.conf import settings

from asgiref.sync import sync_to_async
from pydantic import BaseModel

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.review_hog.backend.reviewer.constants import MAX_CONCURRENT_SANDBOXES
from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext, extract_json_from_text
from products.tasks.backend.services.custom_prompt_multi_turn_runner import MultiTurnSession

logger = logging.getLogger(__name__)

_sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

# Cloud defaults (used when DEBUG=False)
_CLOUD_TEAM_ID = 2
_CLOUD_USER_ID = 196695
_CLOUD_REPOSITORY = "posthog/posthog"
_LOCAL_REPOSITORY = "sortafreel/posthog"


def _resolve_context_for_local_dev(repository: str) -> CustomPromptSandboxContext:
    """Build a sandbox context from the first team/user in the local database.

    Requires a GitHub integration for the team (Task.create_and_run resolves it).
    Inlined here because products/tasks dropped the shared
    ``resolve_sandbox_context_for_local_dev`` helper when the custom-prompt runner
    was refactored into ``custom_prompt_multi_turn_runner``.
    """
    team = Team.objects.select_related("organization").first()
    if not team:
        raise RuntimeError("No team found in local database")

    membership = OrganizationMembership.objects.filter(organization=team.organization).order_by("id").first()
    if not membership:
        raise RuntimeError(f"No users in organization '{team.organization.name}' (team {team.id})")
    user = membership.user

    # Validate the integration exists upfront so we fail early with a clear message.
    gh = Integration.objects.filter(team=team, kind="github").first()
    if not gh:
        raise RuntimeError(
            f"No GitHub integration found for team {team.id}. "
            "Set up a GitHub App installation first: "
            "go to /settings/integrations in your local PostHog."
        )

    return CustomPromptSandboxContext(team_id=team.id, user_id=user.id, repository=repository)


async def _resolve_context() -> CustomPromptSandboxContext:
    """Return sandbox context based on environment (cloud vs local dev)."""
    if settings.DEBUG:
        return await sync_to_async(_resolve_context_for_local_dev)(_LOCAL_REPOSITORY)
    return CustomPromptSandboxContext(
        team_id=_CLOUD_TEAM_ID,
        user_id=_CLOUD_USER_ID,
        repository=_CLOUD_REPOSITORY,
    )


async def _run_prompt(
    prompt: str,
    context: CustomPromptSandboxContext,
    *,
    branch: str | None = None,
    step_name: str = "",
) -> str:
    """Spawn a single-turn sandbox agent and return the agent's final message.

    Thin wrapper over the products/tasks ``MultiTurnSession`` runner. The runner keeps
    the underlying workflow/sandbox alive between turns, so a single-turn caller must
    ``end()`` the session explicitly — otherwise it lingers until the sandbox TTL. The
    full agent log is already persisted by the runner at ``task_run.log_url`` (S3 / Tasks
    UI), so we don't re-read it here.
    """
    session, last_message = await MultiTurnSession.start_raw(
        prompt=prompt,
        context=context,
        branch=branch or None,
        step_name=step_name,
    )
    try:
        return last_message or ""
    finally:
        await session.end()


async def run_sandbox_review(
    prompt: str,
    system_prompt: str,
    branch: str,
    output_path: str,
    model_to_validate: type[BaseModel],
    step_name: str = "",
) -> bool:
    """Run a review in a sandbox and save validated output locally.

    Combines system prompt and user prompt, spawns a sandbox agent,
    extracts JSON from the response, validates with Pydantic, and saves locally.

    Returns True if successful, False otherwise.
    """
    async with _sandbox_semaphore:
        logger.info(f"Acquired sandbox semaphore (limit={MAX_CONCURRENT_SANDBOXES})")

        full_prompt = f"{system_prompt}\n\n{prompt}"
        context = await _resolve_context()

        try:
            last_message = await _run_prompt(prompt=full_prompt, context=context, branch=branch, step_name=step_name)
        except Exception as e:
            logger.exception(f"Sandbox execution failed: {e}")
            return False

        if not last_message:
            logger.error("Sandbox returned no agent message")
            return False

        # Extract JSON, validate, and save
        try:
            json_data = extract_json_from_text(text=last_message, label="Sandbox output")
            validated_data = model_to_validate.model_validate(json_data)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(output_path).open("w") as f:
                f.write(json.dumps(validated_data.model_dump(mode="json"), indent=2))
            logger.info(f"Successfully saved validated data to: {output_path}")
            return True
        except Exception as e:
            error_path = str(output_path).replace(".json", "_error.txt")
            with Path(error_path).open("w") as f:
                f.write(last_message)
            logger.exception(f"Error processing sandbox output: {e}")
            return False
