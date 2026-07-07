import time
import asyncio
import logging
from typing import TypeVar

from asgiref.sync import sync_to_async
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
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    initial_permission_mode: str | None = None,
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

    ``runtime_adapter`` / ``model`` / ``reasoning_effort`` pin the sandbox LLM (e.g. Codex ``gpt-5.5``
    at ``xhigh`` for the perspective review); left ``None`` the step runs on the agent server's
    default (Claude). ``model_to_validate`` is the output *schema*, unrelated to ``model``.
    ``initial_permission_mode`` sets the agent's approval mode — a headless step that calls MCP tools
    under Codex must pass ``"full-access"`` or it stalls on an approval prompt (Codex ``"auto"`` does
    not auto-approve MCP tool calls).

    Forked units (the warm-up+fork arm) do NOT go through here — see ``run_forked_review``.
    """
    full_prompt = f"{system_prompt}\n\n{prompt}"
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=repository,
        model=model,
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
        initial_permission_mode=initial_permission_mode,
        # Review units only ever read over MCP (skill-get / skill-file-get). Read-only strips the
        # write tools entirely — a unit deleted a team's LLMSkill row mid-run before this.
        posthog_mcp_scopes="read_only",
    )
    return await _run_prompt(full_prompt, context, model_to_validate, branch=branch, step_name=step_name)


async def run_forked_review(
    *,
    team_id: int,
    user_id: int,
    repository: str,
    branch: str,
    first_turn_prompt: str,
    review_prompt: str,
    model_to_validate: type[_ModelT],
    step_name: str = "",
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    initial_permission_mode: str | None = None,
    resume_from_run_id: str,
    resume_from_task_id: str | None = None,
) -> _ModelT:
    """Run one review unit forked from another run's session, in two turns.

    Turn 1 sends ``first_turn_prompt`` — which MUST be byte-identical across every sibling forking
    the same source, because a prompt-cache entry is only addressable at its end: siblings share
    the big replayed-transcript prefix only when their entire first request matches the leader's.
    The unit's real ``review_prompt`` (perspective-specific, so necessarily divergent) goes in
    turn 2, riding the already-cached first-turn prefix. Same failure semantics as
    ``run_sandbox_review``: raises so the calling Temporal activity retries; the session is always
    ended.
    """
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=repository,
        model=model,
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
        initial_permission_mode=initial_permission_mode,
        # Review units only ever read over MCP (skill-get / skill-file-get). Read-only strips the
        # write tools entirely — a unit deleted a team's LLMSkill row mid-run before this.
        posthog_mcp_scopes="read_only",
    )
    try:
        session, _ack = await MultiTurnSession.start_raw(
            prompt=first_turn_prompt,
            context=context,
            branch=branch or None,
            step_name=step_name,
            resume_from_run_id=resume_from_run_id,
            resume_from_task_id=resume_from_task_id,
        )
    except Exception:
        logger.exception("Forked sandbox session start failed")
        raise
    try:
        return await session.send_followup(review_prompt, model_to_validate, label=step_name)
    except Exception:
        logger.exception("Forked sandbox review turn failed")
        raise
    finally:
        await session.end()


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
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    initial_permission_mode: str | None = None,
) -> tuple[MultiTurnSession, _ModelT]:
    """Open a multi-turn sandbox session and return it with its first validated turn.

    The caller drives further turns via ``continue_sandbox_session`` and MUST ``end_sandbox_session``
    it (usually in a ``finally``). ``start`` self-ends if the first turn fails to validate, so a raised
    exception never leaves the caller a live session to clean up.

    ``runtime_adapter`` / ``model`` / ``reasoning_effort`` / ``initial_permission_mode`` pin the
    session's LLM exactly like ``run_sandbox_review``'s kwargs; all-``None`` keeps the agent server's
    default. The pin applies to the whole session — every follow-up turn runs on the opener's model.
    """
    full_prompt = f"{system_prompt}\n\n{prompt}"
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=repository,
        model=model,
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
        initial_permission_mode=initial_permission_mode,
        # Review units only ever read over MCP (skill-get / skill-file-get). Read-only strips the
        # write tools entirely — a unit deleted a team's LLMSkill row mid-run before this.
        posthog_mcp_scopes="read_only",
    )
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


async def wait_for_session_transcript(session: MultiTurnSession, *, timeout_seconds: int) -> bool:
    """Wait until the session's raw transcript artifact is on its TaskRun; False on timeout.

    The agent harness uploads the raw session JSONL fire-and-forget at every turn end
    (``transcript-<sessionId>.jsonl``), so after the last turn completes the artifact lands within
    seconds. A forked unit hydrates from this artifact — launching followers before it exists makes
    them fall back to a fresh session, so the warm-up caller must gate on it.
    """

    def _has_transcript() -> bool:
        session.task_run.refresh_from_db(fields=["artifacts"])
        return any(
            artifact.get("name", "").startswith("transcript-") and artifact.get("storage_path")
            for artifact in (session.task_run.artifacts or [])
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if await sync_to_async(_has_transcript, thread_sensitive=False)():
            return True
        await asyncio.sleep(3)
    return False
