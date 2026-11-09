import time
import asyncio

import structlog

from posthog.sync import database_sync_to_async

from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession, turn_failure_error_type
from products.tasks.backend.facade.billing import get_task_run_token_usage

from ...task_profiles import TODAY_NEWS, TODAY_NEWS_MCP_SCOPES
from ...temporal.inputs import MAX_NEWS_ERROR_LENGTH, FailNewsInputs, WriteNewsInputs
from . import agent, editions

logger = structlog.get_logger(__name__)

NEWS_MODEL = "gpt-6-luna"
NEWS_RUNTIME_ADAPTER = "codex"
NEWS_REASONING_EFFORT = "medium"
NEWS_PERMISSION_MODE = "full-access"
NEWS_AI_STAGE = "today_news"
NEWS_MAX_POLL_SECONDS = 10 * 60
MICRO_USD = 1_000_000


async def write_edition(inputs: WriteNewsInputs) -> None:
    assignment = await database_sync_to_async(editions.assignment)(inputs)
    if assignment is None:
        return
    started = time.monotonic()
    session: MultiTurnSession | None = None
    try:
        session, output = await MultiTurnSession.start(
            prompt=agent.prompt(assignment),
            context=CustomPromptSandboxContext(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                posthog_mcp_scopes=TODAY_NEWS_MCP_SCOPES,
                github_read_access=False,
                model=NEWS_MODEL,
                runtime_adapter=NEWS_RUNTIME_ADAPTER,
                reasoning_effort=NEWS_REASONING_EFFORT,
                initial_permission_mode=NEWS_PERMISSION_MODE,
            ),
            model=agent.NewsAgentOutput,
            step_name=NEWS_AI_STAGE,
            profile=TODAY_NEWS,
            ai_stage=NEWS_AI_STAGE,
            max_poll_seconds=NEWS_MAX_POLL_SECONDS,
            json_retry_prompt=agent.JSON_RETRY_PROMPT,
            fallback_from_text=None,
            output_schema=agent.NewsAgentOutput.model_json_schema(),
        )
        edition = agent.stored_edition(output, assignment.withheld_surveys)
        await database_sync_to_async(editions.store_edition)(inputs, edition, NEWS_MODEL)
        await session.end()
    except asyncio.CancelledError:
        await _end_failed(session, "cancelled")
        raise
    except Exception as error:
        logger.warning("today_news_agent_failed", team_id=inputs.team_id, error=str(error), exc_info=True)
        await _end_failed(session, str(error), turn_failure_error_type(error))
        await database_sync_to_async(editions.mark_failed)(
            FailNewsInputs(
                team_id=inputs.team_id,
                edition_id=inputs.edition_id,
                error=str(error)[:MAX_NEWS_ERROR_LENGTH],
                claimed_at=inputs.claimed_at,
            )
        )
        report = editions.NewsRunReport(
            outcome="failed",
            seconds=time.monotonic() - started,
            model=NEWS_MODEL,
            task_run_id=_run_id(session),
        )
    else:
        report = await database_sync_to_async(_report)(inputs, session, edition, time.monotonic() - started)
    await database_sync_to_async(editions.capture_written)(inputs, report)


def _run_id(session: MultiTurnSession | None) -> str | None:
    return str(session.task_run.id) if session is not None else None


def _report(
    inputs: WriteNewsInputs, session: MultiTurnSession, edition: agent.StoredEdition | None, seconds: float
) -> editions.NewsRunReport:
    usage = get_task_run_token_usage(run_id=session.task_run.id, team_id=inputs.team_id)
    return editions.NewsRunReport(
        outcome="ready" if edition is not None else "quiet",
        seconds=seconds,
        model=NEWS_MODEL,
        items=edition.items() if edition is not None else 0,
        task_run_id=str(session.task_run.id),
        cost_usd=usage.cost_microusd / MICRO_USD if usage.cost_microusd is not None else None,
        cost_complete=usage.complete,
    )


async def _end_failed(session: MultiTurnSession | None, error: str, error_type: str | None = None) -> None:
    if session is None:
        return
    await asyncio.shield(session.end(status="failed", error=error, error_type=error_type))
