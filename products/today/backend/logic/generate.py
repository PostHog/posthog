"""Generating a briefing: one sandbox agent run that gathers the person's data over MCP and writes the result."""

from datetime import timedelta

import structlog

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

from ..facade.enums import BriefingStatus
from ..feature_flags import is_enabled_for
from ..models import DailyBriefing
from .prompt import build_prompt

logger = structlog.get_logger(__name__)

MODEL = "gpt-6-luna"
RUNTIME_ADAPTER = "codex"
REASONING_EFFORT = "medium"
# A briefing is a few tool calls and a short text; a run past this is stuck.
AGENT_TIMEOUT = timedelta(minutes=20)
SANDBOX_ENV_NAME = "today-briefing"


def _load(team_id: int, briefing_id: str) -> tuple[DailyBriefing, Team, User]:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    team = Team.objects.select_related("organization").get(id=briefing.team_id)
    user = User.objects.get(id=briefing.user_id)
    return briefing, team, user


def _prepare(team_id: int, briefing_id: str) -> tuple[CustomPromptSandboxContext, str] | None:
    """The sandbox context and the prompt, or None when the person may not get a briefing.

    The flag can turn off after the row was created, so the row is deleted then: a briefing
    nobody can open is not worth a sandbox.
    """
    briefing, team, user = _load(team_id, briefing_id)
    if not is_enabled_for(user, team) or not team.organization.is_ai_data_processing_approved:
        briefing.delete()
        return None
    briefing.status = BriefingStatus.WRITING
    briefing.save(update_fields=["status"])
    sandbox_environment_id = str(
        tasks_facade.upsert_internal_sandbox_env(
            team.id, SANDBOX_ENV_NAME, tasks_facade.SandboxNetworkAccessLevel.TRUSTED
        )
    )
    context = CustomPromptSandboxContext(
        team_id=team.id,
        user_id=user.id,
        sandbox_environment_id=sandbox_environment_id,
        posthog_mcp_scopes="today_briefing",
        model=MODEL,
        runtime_adapter=RUNTIME_ADAPTER,
        reasoning_effort=REASONING_EFFORT,
        # Headless: the agent must be able to call the write tool without anyone approving it.
        initial_permission_mode="full-access",
    )
    return context, build_prompt(briefing, user)


def _is_written(team_id: int, briefing_id: str) -> bool:
    return DailyBriefing.objects.for_team(team_id).filter(id=briefing_id, status=BriefingStatus.READY).exists()


async def run_agent(*, team_id: int, briefing_id: str) -> None:
    """Run the briefing agent to completion. Raises when it finished without storing a briefing."""
    prepared = await database_sync_to_async(_prepare, thread_sensitive=False)(team_id, briefing_id)
    if prepared is None:
        return
    context, prompt = prepared
    session, reply = await MultiTurnSession.start_raw(
        prompt,
        context,
        step_name="today_briefing",
        origin_product=tasks_facade.TaskOriginProduct.POSTHOG_AI,
        ai_stage="today_briefing",
        ai_agent_name="today-briefing",
        internal=True,
        max_poll_seconds=int(AGENT_TIMEOUT.total_seconds()),
    )
    await session.end()
    if not await database_sync_to_async(_is_written, thread_sensitive=False)(team_id, briefing_id):
        logger.warning("today_agent_did_not_write", team_id=team_id, briefing_id=briefing_id, reply=reply[:500])
        raise RuntimeError("The agent finished without storing the briefing.")


def mark_failed(*, team_id: int, briefing_id: str, error: str) -> None:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    briefing.status = BriefingStatus.FAILED
    briefing.error = error[:1000]
    briefing.save(update_fields=["status", "error"])
