import asyncio
import logging
import contextvars
from typing import TypeVar

from pydantic import BaseModel

from posthog.models.integration import Integration

from products.review_hog.backend.reviewer.constants import MAX_CONCURRENT_SANDBOXES
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

_ModelT = TypeVar("_ModelT", bound=BaseModel)

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
    model: type[_ModelT],
    *,
    branch: str | None = None,
    step_name: str = "",
) -> _ModelT | None:
    """Spawn a single-turn sandbox agent and return its validated end-of-turn, or None on failure.

    Thin wrapper over the products/tasks ``MultiTurnSession.start(model=)``, which runs the agent
    and validates its end-of-turn JSON against ``model`` internally. On a sandbox error or a
    parse/validation failure ``start`` ends the session itself and raises, so we log and return
    None. On success the runner keeps the workflow/sandbox alive between turns, so a single-turn
    caller must ``end()`` it explicitly — otherwise it lingers until the sandbox TTL. The full agent
    log is already persisted by the runner at ``task_run.log_url`` (S3 / Tasks UI).
    """
    try:
        session, parsed = await MultiTurnSession.start(
            prompt=prompt,
            context=context,
            model=model,
            branch=branch or None,
            step_name=step_name,
        )
    except Exception:
        logger.exception("Sandbox execution failed")
        return None
    try:
        return parsed
    finally:
        await session.end()


async def run_sandbox_review(
    prompt: str,
    system_prompt: str,
    branch: str,
    repository: str,
    model_to_validate: type[_ModelT],
    step_name: str = "",
) -> _ModelT | None:
    """Run one review step in a sandbox and return its validated output.

    Combines the system and user prompts, spawns a single-turn sandbox agent under the global
    concurrency cap, and returns the agent's end-of-turn parsed into ``model_to_validate`` — or
    None if the sandbox errored or its output failed to validate. Persistence is the caller's job;
    this helper holds no filesystem state.
    """
    async with _sandbox_semaphore:
        logger.info(f"Acquired sandbox semaphore (limit={MAX_CONCURRENT_SANDBOXES})")
        full_prompt = f"{system_prompt}\n\n{prompt}"
        context = _sandbox_context_for(repository)
        return await _run_prompt(full_prompt, context, model_to_validate, branch=branch, step_name=step_name)
