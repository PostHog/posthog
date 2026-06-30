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
) -> _ModelT:
    """Spawn a single-turn sandbox agent and return its validated end-of-turn.

    Thin wrapper over the products/tasks ``MultiTurnSession.start(model=)``, which runs the agent
    and validates its end-of-turn JSON against ``model`` internally. On a sandbox error or a
    parse/validation failure ``start`` ends the session itself and raises — we log it for the worker
    trail and re-raise so the calling Temporal activity fails and is retried (swallowing it would
    make Temporal see a "success" and never retry the transient flake). On success the runner keeps
    the workflow/sandbox alive between turns, so a single-turn caller must ``end()`` it explicitly —
    otherwise it lingers until the sandbox TTL. The full agent log is already persisted by the
    runner at ``task_run.log_url`` (S3 / Tasks UI).
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
        raise
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
) -> _ModelT:
    """Run one review step in a sandbox and return its validated output.

    Spawns a single-turn sandbox agent for ``(team_id, user_id)`` against ``repository`` (cloned and
    checked out at ``branch``, same as Signals report research) and returns the agent's end-of-turn
    parsed into ``model_to_validate``, raising if the sandbox errored or its output failed to
    validate (so the calling Temporal activity retries). Identity is passed **explicitly** (no
    ambient ContextVar) so it crosses Temporal
    worker boundaries cleanly and can't bleed between tenants. Throttling is the caller's job (the
    Temporal fan-out bounds concurrency per child workflow); persistence is the caller's job too —
    this helper holds no filesystem state.
    """
    full_prompt = f"{system_prompt}\n\n{prompt}"
    context = CustomPromptSandboxContext(team_id=team_id, user_id=user_id, repository=repository)
    return await _run_prompt(full_prompt, context, model_to_validate, branch=branch, step_name=step_name)


async def start_sandbox_session(
    *,
    team_id: int,
    user_id: int,
    repository: str,
    branch: str,
    prompt: str,
    system_prompt: str,
    model_to_validate: type[_ModelT],
    step_name: str = "",
) -> tuple[MultiTurnSession, _ModelT]:
    """Open a multi-turn sandbox session and return it with its first validated turn.

    The caller drives further turns via ``continue_sandbox_session`` and MUST ``end_sandbox_session``
    it (usually in a ``finally``). ``start`` self-ends if the first turn fails to validate, so a raised
    exception never leaves the caller a live session to clean up.
    """
    full_prompt = f"{system_prompt}\n\n{prompt}"
    context = CustomPromptSandboxContext(team_id=team_id, user_id=user_id, repository=repository)
    try:
        return await MultiTurnSession.start(
            prompt=full_prompt,
            context=context,
            model=model_to_validate,
            branch=branch or None,
            step_name=step_name,
        )
    except Exception:
        logger.exception("Sandbox session start failed")
        raise


async def continue_sandbox_session(
    session: MultiTurnSession,
    *,
    prompt: str,
    model_to_validate: type[_ModelT],
    label: str = "",
) -> _ModelT:
    """Run a follow-up turn on a live session and return its validated output.

    The session already holds the prior turns' context, so the prompt carries only the new ask (no
    system prompt). Raises on failure — the caller's ``finally`` ends the session.
    """
    try:
        return await session.send_followup(prompt, model_to_validate, label=label)
    except Exception:
        logger.exception("Sandbox session follow-up failed")
        raise


async def end_sandbox_session(session: MultiTurnSession) -> None:
    """End a session opened by ``start_sandbox_session`` (call in a ``finally``)."""
    await session.end()
