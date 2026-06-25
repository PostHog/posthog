import logging
from typing import TypeVar

from pydantic import BaseModel

from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

_ModelT = TypeVar("_ModelT", bound=BaseModel)

logger = logging.getLogger(__name__)


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
    *,
    team_id: int,
    user_id: int,
    repository: str,
    branch: str,
    prompt: str,
    system_prompt: str,
    model_to_validate: type[_ModelT],
    step_name: str = "",
) -> _ModelT | None:
    """Run one review step in a sandbox and return its validated output.

    Spawns a single-turn sandbox agent for ``(team_id, user_id)`` against ``repository`` (cloned and
    checked out at ``branch``, same as Signals report research) and returns the agent's end-of-turn
    parsed into ``model_to_validate`` — or None if the sandbox errored or its output failed to
    validate. Identity is passed **explicitly** (no ambient ContextVar) so it crosses Temporal
    worker boundaries cleanly and can't bleed between tenants. Throttling is the caller's job (the
    Temporal fan-out bounds concurrency per child workflow); persistence is the caller's job too —
    this helper holds no filesystem state.
    """
    full_prompt = f"{system_prompt}\n\n{prompt}"
    context = CustomPromptSandboxContext(team_id=team_id, user_id=user_id, repository=repository)
    return await _run_prompt(full_prompt, context, model_to_validate, branch=branch, step_name=step_name)
