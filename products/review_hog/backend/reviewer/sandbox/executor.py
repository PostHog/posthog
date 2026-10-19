import re
import uuid
import hashlib
import logging
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from products.review_hog.backend.reviewer.constants import REVIEW_MCP_SCOPES
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.facade.api import TaskOriginProduct
from products.tasks.backend.facade.contracts import SessionFile

_ModelT = TypeVar("_ModelT", bound=BaseModel)

logger = logging.getLogger(__name__)

TASK_ORIGIN_KEY_MAX_LENGTH = 128

_REVIEW_PR_WORKFLOW_ID = re.compile(r"^(?P<kind>review-pr:\d+:)(?P<repository>[^:]+)(?P<pr>:\d+)(?P<step>.*)$")


def _origin_key(workflow_id_prefix: str | None) -> str | None:
    # Task.origin_key reaches $ai_generation as task_origin_key, and the workflow id holds the PR.
    # Task allows one origin_key per team, so the unique part leads and survives truncation.
    if not workflow_id_prefix:
        return None
    unique = uuid.uuid4().hex[:12]
    key = f"{unique}:{workflow_id_prefix}"
    match = _REVIEW_PR_WORKFLOW_ID.match(workflow_id_prefix)
    if len(key) <= TASK_ORIGIN_KEY_MAX_LENGTH or match is None:
        return key[:TASK_ORIGIN_KEY_MAX_LENGTH]
    # Only the step may be cut, so a long owner/repo becomes a stable digest that keeps PRs apart.
    repository = match["repository"]
    pr_identity = f"{unique}:{match['kind']}{repository}{match['pr']}"
    if len(pr_identity) > TASK_ORIGIN_KEY_MAX_LENGTH:
        digest = hashlib.sha256(repository.encode()).hexdigest()[:16]
        pr_identity = f"{unique}:{match['kind']}{digest}{match['pr']}"
    return f"{pr_identity}{match['step']}"[:TASK_ORIGIN_KEY_MAX_LENGTH]


# Sent once when the agent ends its first turn with prose instead of the JSON the step needs.
JSON_RETRY_PROMPT = (
    "Your last reply did not contain the JSON object the task asks for. "
    "Reply now with only that JSON object, matching the schema above. Do not add prose or code fences."
)


async def _run_prompt(
    prompt: str,
    context: CustomPromptSandboxContext,
    model: type[_ModelT],
    *,
    branch: str | None = None,
    step_name: str = "",
    workflow_id_prefix: str | None = None,
    files: Sequence[SessionFile] = (),
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
            workflow_id_prefix=workflow_id_prefix,
            origin_key=_origin_key(workflow_id_prefix),
            # ReviewHog-attributed and internal (pipeline plumbing, not a user-facing task); the step
            # lands on $ai_generation as ai_stage for per-stage cost attribution.
            origin_product=TaskOriginProduct.REVIEW_HOG,
            internal=True,
            ai_stage=step_name or None,
            json_retry_prompt=JSON_RETRY_PROMPT,
            files=files,
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
    workflow_id_prefix: str | None = None,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    initial_permission_mode: str | None = None,
    files: Sequence[SessionFile] = (),
    codex_max_subagents: int | None = None,
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
    not auto-approve MCP tool calls). ``files`` go into the sandbox before the first turn, and
    ``codex_max_subagents`` lets a step that starts Codex sub-agents run more of them at once.
    """
    full_prompt = "\n\n".join(part for part in (system_prompt, prompt) if part)
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=repository,
        model=model,
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
        codex_max_subagents=codex_max_subagents,
        # Coordinator sub-agents carry no prompt cache marker, so only the run-wide scope shares their prefix.
        codex_shared_prompt_cache=True,
        initial_permission_mode=initial_permission_mode,
        # Unset means "full" — never hand that to a session fed untrusted PR-comment text.
        posthog_mcp_scopes=REVIEW_MCP_SCOPES,
    )
    return await _run_prompt(
        full_prompt,
        context,
        model_to_validate,
        branch=branch,
        step_name=step_name,
        workflow_id_prefix=workflow_id_prefix,
        files=files,
    )


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
    workflow_id_prefix: str | None = None,
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
    full_prompt = "\n\n".join(part for part in (system_prompt, prompt) if part)
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=repository,
        model=model,
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
        codex_shared_prompt_cache=True,
        initial_permission_mode=initial_permission_mode,
        # Unset means "full" — never hand that to a session fed untrusted PR-comment text.
        posthog_mcp_scopes=REVIEW_MCP_SCOPES,
    )
    try:
        return await MultiTurnSession.start(
            prompt=full_prompt,
            context=context,
            model=model_to_validate,
            branch=branch or None,
            step_name=step_name,
            workflow_id_prefix=workflow_id_prefix,
            origin_key=_origin_key(workflow_id_prefix),
            # Same attribution trio as _run_prompt: ReviewHog-origin, internal, step as ai_stage.
            origin_product=TaskOriginProduct.REVIEW_HOG,
            internal=True,
            ai_stage=step_name or None,
            json_retry_prompt=JSON_RETRY_PROMPT,
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


async def end_sandbox_session(
    session: MultiTurnSession, *, status: str = "completed", error: str | None = None
) -> None:
    """End a session opened by ``start_sandbox_session`` (call in a ``finally``).

    Pass ``status="failed"`` (with ``error``) when tearing down after a failed turn, so the
    underlying TaskRun isn't recorded as completed and run-status metrics stay honest.
    """
    await session.end(status=status, error=error)
