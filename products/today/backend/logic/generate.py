"""Generating a briefing: one read-only sandbox agent run that gathers the person's data over MCP and answers with the text."""

from datetime import timedelta
from typing import Protocol
from uuid import UUID

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

from ..facade.enums import BriefingStatus
from ..feature_flags import is_enabled_for
from ..models import DailyBriefing
from .agent_output import BriefingOutput, problems_with, to_content, to_fact_sheet
from .briefings import store_briefing
from .prompt import build_prompt, recent_briefings

logger = structlog.get_logger(__name__)

MODEL = "gpt-6-luna"
RUNTIME_ADAPTER = "codex"
REASONING_EFFORT = "medium"
# A briefing is a few tool calls and a short text; a run past this is stuck.
AGENT_TIMEOUT = timedelta(minutes=20)
# Answers the agent gets to fix a briefing that broke the writing rules, the first one included.
WRITE_ATTEMPTS = 3
SANDBOX_ENV_NAME = "today-briefing"


class _HasTaskId(Protocol):
    @property
    def task_id(self) -> UUID: ...


def _load(team_id: int, briefing_id: str) -> tuple[DailyBriefing, Team, User]:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    team = Team.objects.select_related("organization").get(id=briefing.team_id)
    user = User.objects.get(id=briefing.user_id)
    return briefing, team, user


def _title(briefing: DailyBriefing) -> str:
    return f"Today briefing, {briefing.local_day.isoformat()} {briefing.edition}"


def _preranked_reports(team: Team, user: User) -> list[signals.BriefingReport]:
    """The reports PostHog already ranked for the person. A failure here costs the agent its head start, not the run."""
    try:
        return signals.reports_for_briefing(team_id=team.id, user_id=user.id)
    except Exception as error:
        capture_exception(error, {"team_id": team.id, "product": "today"})
        return []


def _prepare(team_id: int, briefing_id: str) -> tuple[CustomPromptSandboxContext, str, str] | None:
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
        posthog_mcp_scopes="read_only",
        model=MODEL,
        runtime_adapter=RUNTIME_ADAPTER,
        reasoning_effort=REASONING_EFFORT,
        # Headless: the agent's read tools must run without anyone approving them.
        initial_permission_mode="full-access",
    )
    prompt = build_prompt(briefing, user, _preranked_reports(team, user), recent_briefings(briefing))
    return context, prompt, _title(briefing)


def _fix_message(problems: list[str]) -> str:
    return (
        "Your briefing broke these rules. Fix all of them and answer again with the whole briefing in the same shape:\n- "
        + "\n- ".join(problems)
    )


def _store(team_id: int, briefing_id: str, output: BriefingOutput) -> list[str]:
    """Store the agent's answer, or return the rules it broke so the agent can fix them."""
    briefing, _team, user = _load(team_id, briefing_id)
    problems = problems_with(output, briefing, user)
    if not problems:
        store_briefing(briefing, to_fact_sheet(output, briefing, user), to_content(output))
    return problems


async def run_agent(*, team_id: int, briefing_id: str) -> None:
    """Run the briefing agent to completion and store what it wrote.

    The agent answers in `BriefingOutput`. An answer that breaks the writing rules goes back to it
    as a follow-up turn in the same sandbox, a few times; after that the run fails.
    """
    prepared = await database_sync_to_async(_prepare, thread_sensitive=False)(team_id, briefing_id)
    if prepared is None:
        return
    context, prompt, title = prepared

    async def name_the_task(task_run: _HasTaskId) -> None:
        # The run shows in the person's session list, so it carries a name instead of the prompt's first line.
        await database_sync_to_async(tasks_facade.set_task_title, thread_sensitive=False)(
            task_run.task_id, team_id, title
        )

    session, output = await MultiTurnSession.start(
        prompt,
        context,
        model=BriefingOutput,
        step_name="today_briefing",
        origin_product=tasks_facade.TaskOriginProduct.POSTHOG_AI,
        ai_stage="today_briefing",
        ai_agent_name="today-briefing",
        on_task_run_created=name_the_task,
        max_poll_seconds=int(AGENT_TIMEOUT.total_seconds()),
        output_schema=BriefingOutput.model_json_schema(),
    )
    try:
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            problems = await database_sync_to_async(_store, thread_sensitive=False)(team_id, briefing_id, output)
            if not problems:
                break
            if attempt == WRITE_ATTEMPTS:
                raise RuntimeError("The agent's briefing kept breaking the rules: " + "; ".join(problems))
            output = await session.send_followup(_fix_message(problems), BriefingOutput, label=f"fix_{attempt}")
    except Exception as error:
        await session.end(status="failed", error=str(error)[:500])
        raise
    await session.end()


def mark_failed(*, team_id: int, briefing_id: str, error: str) -> None:
    briefing = DailyBriefing.objects.for_team(team_id).get(id=briefing_id)
    briefing.status = BriefingStatus.FAILED
    briefing.error = error[:1000]
    briefing.save(update_fields=["status", "error"])
