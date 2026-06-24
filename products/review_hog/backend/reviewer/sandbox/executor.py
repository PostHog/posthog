import json
import asyncio
import logging
import contextvars
from pathlib import Path

from pydantic import BaseModel

from posthog.models.integration import Integration

from products.review_hog.backend.reviewer.constants import MAX_CONCURRENT_SANDBOXES
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession, extract_json_from_text

logger = logging.getLogger(__name__)

_sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

# Run-scoped sandbox identity (team_id, user_id), bound once per review by `bind_sandbox_identity`
# and read by every sandbox call to build its context. The ids are an explicit input from the entry
# point (the `run_review` CLI today; the Temporal trigger — the PR's author and their team — later),
# so there is no environment-switched or hardcoded fallback.
_sandbox_identity: contextvars.ContextVar[tuple[int, int]] = contextvars.ContextVar("review_hog_sandbox_identity")


async def bind_sandbox_identity(*, team_id: int, user_id: int) -> None:
    """Validate the team's GitHub integration and bind ``(team_id, user_id)`` for this run's sandboxes.

    Called once at the start of a review in the orchestrator's own task context, so the value
    propagates into the `asyncio.gather` fan-out (tasks copy the context at creation).
    ``Task.create_and_run`` needs a ``kind="github"`` integration for the team, so we fail fast with
    setup guidance if it's missing.
    """
    if not await Integration.objects.filter(team_id=team_id, kind="github").aexists():
        raise RuntimeError(
            f"No GitHub integration found for team {team_id}. "
            "Set up a GitHub App installation first (Settings → Integrations)."
        )
    _sandbox_identity.set((team_id, user_id))


def _sandbox_context_for(repository: str) -> CustomPromptSandboxContext:
    """Build the sandbox context for ``repository`` from the run's bound identity.

    The sandbox clones ``repository`` (the PR's own ``owner/repo``) and checks out the PR branch, so
    reviews run against the real repo — same as Signals report research.
    """
    try:
        team_id, user_id = _sandbox_identity.get()
    except LookupError:
        raise RuntimeError(
            "Sandbox identity not bound — call bind_sandbox_identity() at the start of the run"
        ) from None
    return CustomPromptSandboxContext(team_id=team_id, user_id=user_id, repository=repository)


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
    repository: str,
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
        context = _sandbox_context_for(repository)

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
