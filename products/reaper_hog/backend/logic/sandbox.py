import logging
from typing import TypeVar

from pydantic import BaseModel

from products.reaper_hog.backend.logic.constants import REAPER_MCP_SCOPES
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.facade.api import TaskOriginProduct

_ModelT = TypeVar("_ModelT", bound=BaseModel)

logger = logging.getLogger(__name__)


async def start_session(
    *,
    team_id: int,
    user_id: int,
    repository: str,
    branch: str,
    prompt: str,
    system_prompt: str,
    model_to_validate: type[_ModelT],
    step_name: str,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    initial_permission_mode: str | None = None,
) -> tuple[MultiTurnSession, _ModelT]:
    context = CustomPromptSandboxContext(
        team_id=team_id,
        user_id=user_id,
        repository=repository,
        model=model,
        runtime_adapter=runtime_adapter,
        reasoning_effort=reasoning_effort,
        initial_permission_mode=initial_permission_mode,
        posthog_mcp_scopes=REAPER_MCP_SCOPES,
    )
    try:
        return await MultiTurnSession.start(
            prompt=f"{system_prompt}\n\n{prompt}",
            context=context,
            model=model_to_validate,
            branch=branch,
            step_name=step_name,
            origin_product=TaskOriginProduct.REAPER_HOG,
            internal=True,
            ai_stage=step_name,
        )
    except Exception:
        logger.exception("Sandbox session start failed")
        raise


async def continue_session(
    session: MultiTurnSession, *, prompt: str, model_to_validate: type[_ModelT], label: str
) -> _ModelT:
    try:
        return await session.send_followup(prompt, model_to_validate, label=label)
    except Exception:
        logger.exception("Sandbox session follow-up failed")
        raise


async def end_session(session: MultiTurnSession, *, status: str = "completed", error: str | None = None) -> None:
    await session.end(status=status, error=error)
