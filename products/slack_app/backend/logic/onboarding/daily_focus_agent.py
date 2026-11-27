"""The daily work focus as one agent run, instead of the search, the classifiers and the channel index.

The agent reads Slack through the person's own Slack MCP, so it sees what the person can see, not only the channels
the bot is in. The run mounts that one server and nothing else, and the Slack MCP token holds read scopes only, so a
message that tells the agent to post or to reach another tool has nothing to act through. The agent answers once,
validated against `DailyFocusAgentOutput`, and the code below checks that answer again before it renders the same DM
the pipeline sends.
"""

import asyncio
import functools
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template, select_autoescape
from pydantic import BaseModel, Field

from products.mcp_store.backend.facade.api import slack_mcp_installation_id
from products.slack_app.backend.feature_flags import is_slack_app_daily_focus_agent_enabled
from products.slack_app.backend.logic.daily_focus import resolve_daily_focus
from products.slack_app.backend.logic.onboarding.step import OnboardingContext
from products.slack_app.backend.logic.onboarding.work_focus import (
    MAX_INTRO_CHARS,
    MAX_OFFER_CHARS,
    MAX_REQUEST_CHARS,
    MAX_SUGGESTIONS,
    MAX_SUMMARY_CHARS,
    MAX_SUMMARY_ITEMS,
    WorkFocus,
    WorkFocusSuggestion,
    WorkFocusSummaryItem,
    send_agent_daily_focus,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.task_profiles import DAILY_FOCUS
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession

logger = structlog.get_logger(__name__)

AGENT_MODEL = "zai-org/glm-5.3-flash"
AGENT_RUNTIME_ADAPTER = "claude"
# Below the activity's timeout, so a slow run ends as a failure the code sees instead of a cancelled activity.
AGENT_POLL_SECONDS = 8 * 60
# The agent only reads Slack and answers, so it needs a fraction of the default 4 CPU / 16 GB box. A backend that
# reserves the whole box bills for all of it.
AGENT_CPU_CORES = 2
AGENT_MEMORY_GB = 4

PROMPTS_DIR = Path(__file__).parent / "prompts"


class AgentSummaryItem(BaseModel):
    text: str
    channel_id: str
    permalink: str | None = None
    # Required, so the agent states it for every item and the code can drop what is resolved.
    resolved: bool


class AgentSuggestion(BaseModel):
    offer: str
    request: str
    source_permalink: str | None = None
    source_author_id: str | None = None
    source_channel_name: str | None = None
    resolved: bool


class DailyFocusAgentOutput(BaseModel):
    intro: str = ""
    summary: list[AgentSummaryItem] = Field(default_factory=list)
    suggestions: list[AgentSuggestion] = Field(default_factory=list)


def agent_owner_id(integration: WorkspaceIntegration, slack_user_id: str) -> int | None:
    """The PostHog user the run acts as and whose Slack MCP it mounts, when the agent flag is on for them and their
    Slack MCP works. None keeps the person on the pipeline."""
    user = OnboardingContext(integration=integration, slack_user_id=slack_user_id).posthog_user
    if user is None or not is_slack_app_daily_focus_agent_enabled(integration, user.distinct_id):
        return None
    return user.id if slack_mcp_installation_id(integration.team_id, user.id) else None


def start_daily_focus_agent(
    integration: WorkspaceIntegration, slack_user_id: str, *, since: datetime, run_at: datetime
) -> None:
    """Starts the agent workflow for one claimed run. The id names the run, so a retry of the daily activity finds
    the workflow it started instead of starting a second agent."""
    # Deferred so temporalio stays off the import path of the daily focus logic.
    from temporalio.common import WorkflowIDConflictPolicy  # noqa: PLC0415

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.slack_app.backend.temporal.slack_app_work_focus import (
        SlackAppDailyFocusAgentWorkflow,  # noqa: PLC0415
    )
    from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs  # noqa: PLC0415

    inputs = SlackAppWorkFocusInputs(
        integration_id=integration.id,
        slack_team_id=integration.integration_id,
        slack_user_id=slack_user_id,
        since=int(since.timestamp()),
        run_at=int(run_at.timestamp()),
    )
    asyncio.run(
        sync_connect().start_workflow(
            SlackAppDailyFocusAgentWorkflow.run,
            inputs,
            id=f"slack-app-daily-focus-agent-{inputs.slack_team_id}-{slack_user_id}-{inputs.run_at}",
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    )


def to_work_focus(output: DailyFocusAgentOutput, slack_user_id: str) -> WorkFocus:
    """The agent's answer within the limits the pipeline holds itself to. Anything the agent marked resolved is
    dropped, whatever the prompt said. So is a link that is not a Slack link, and an offer whose source the person
    wrote, because they already know about their own work."""
    summary = [
        WorkFocusSummaryItem(
            text=item.text.strip()[:MAX_SUMMARY_CHARS],
            channel_id=item.channel_id,
            permalink=_slack_link(item.permalink),
        )
        for item in output.summary
        if not item.resolved and item.text.strip() and item.channel_id[:1] in ("C", "G")
    ][:MAX_SUMMARY_ITEMS]
    suggestions = [
        WorkFocusSuggestion(
            offer=item.offer.strip()[:MAX_OFFER_CHARS],
            request=item.request.strip()[:MAX_REQUEST_CHARS],
            source_permalink=_slack_link(item.source_permalink),
            source_author_id=item.source_author_id,
            source_channel_name=item.source_channel_name,
        )
        for item in output.suggestions
        if not item.resolved and item.offer.strip() and item.request.strip() and item.source_author_id != slack_user_id
    ][:MAX_SUGGESTIONS]
    return WorkFocus(intro=output.intro.strip()[:MAX_INTRO_CHARS], suggestions=suggestions, summary=summary)


def _slack_link(value: str | None) -> str | None:
    return value if value and value.startswith("https://") and ".slack.com/" in value else None


def run_daily_focus_agent(
    integration: WorkspaceIntegration, slack_user_id: str, *, since: datetime, run_at: datetime, zone: ZoneInfo
) -> str:
    """One day's work focus through the agent. The send guard is the pipeline's, so a retry never sends twice."""
    daily = resolve_daily_focus(integration.integration_id, slack_user_id)
    if not daily.enabled:
        return "turned_off"
    if daily.last_run_at != run_at:
        return "superseded"
    if daily.already_sent:
        return "already_sent"
    owner_id = agent_owner_id(integration, slack_user_id)
    if owner_id is None:
        return "agent_unavailable"
    installation_id = slack_mcp_installation_id(integration.team_id, owner_id)
    if installation_id is None:
        return "agent_unavailable"
    output = asyncio.run(_ask_agent(integration, slack_user_id, owner_id, installation_id, since=since, zone=zone))
    focus = to_work_focus(output, slack_user_id)
    if not focus.summary and not focus.suggestions:
        return "nothing_actionable"
    return send_agent_daily_focus(integration, slack_user_id, focus, at=daily.at, zone=zone, run_at=run_at, since=since)


async def _ask_agent(
    integration: WorkspaceIntegration,
    slack_user_id: str,
    owner_id: int,
    installation_id: str,
    *,
    since: datetime,
    zone: ZoneInfo,
) -> DailyFocusAgentOutput:
    prompt = _prompt_template().render(
        person=f"<@{slack_user_id}>",
        since=since.astimezone(zone).strftime("%A %H:%M"),
        zone=zone.key,
        max_summary_items=MAX_SUMMARY_ITEMS,
        max_suggestions=MAX_SUGGESTIONS,
    )
    session, output = await MultiTurnSession.start(
        prompt=prompt,
        context=CustomPromptSandboxContext(
            team_id=integration.team_id,
            user_id=owner_id,
            posthog_mcp_scopes="read_only",
            model=AGENT_MODEL,
            runtime_adapter=AGENT_RUNTIME_ADAPTER,
        ),
        model=DailyFocusAgentOutput,
        profile=DAILY_FOCUS,
        step_name="slack_daily_focus",
        ai_stage="slack_app_daily_focus",
        max_poll_seconds=AGENT_POLL_SECONDS,
        mcp_credential_owner_id=owner_id,
        # The loop connector snapshot: the run mounts the person's Slack MCP and none of their other connections.
        before_task_dispatch=lambda _run_id: {
            "config_snapshot": {"connectors": {"mcp_installation_ids": [installation_id]}},
            "sandbox_cpu_cores": AGENT_CPU_CORES,
            "sandbox_memory_gb": AGENT_MEMORY_GB,
        },
        output_schema=DailyFocusAgentOutput.model_json_schema(),
    )
    try:
        return output
    finally:
        await session.end()


@functools.cache
def _prompt_template() -> Template:
    # StrictUndefined, so a variable the template names and the call forgets fails the run instead of sending blanks.
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR), autoescape=select_autoescape(), undefined=StrictUndefined)
    return env.get_template("daily_focus_agent.jinja")
