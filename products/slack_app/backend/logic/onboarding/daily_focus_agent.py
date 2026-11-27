"""The daily work focus as one agent run, instead of the search, the classifiers and the channel index.

The agent reads Slack through the person's own Slack MCP, so it sees what the person can see, not only the channels
the bot is in. Every message it reads is untrusted input. The run mounts only that server, and the MCP Store answers
the run's token for that connection alone. The Slack MCP token holds read scopes only, and the sandbox reaches
infrastructure hosts only and holds no GitHub credential. The agent answers once, validated against
`DailyFocusAgentOutput`, and the code below checks that answer again before it renders the same DM the pipeline
sends.
"""

import re
import asyncio
import functools
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template, select_autoescape
from pydantic import BaseModel, Field

from posthog.models.integration import SlackIntegration

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
    WorkFocus,
    WorkFocusSuggestion,
    WorkFocusSummaryItem,
    send_agent_daily_focus,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.task_profiles import DAILY_FOCUS
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.facade.model_catalogue import model_allowed_by_product_pin
from products.tasks.backend.facade.profiles import GithubAccess

logger = structlog.get_logger(__name__)

AGENT_MODEL = "zai-org/glm-5.3-flash"
AGENT_RUNTIME_ADAPTER = "claude"
# Below the activity's timeout, so a slow run ends as a failure the code sees instead of a cancelled activity.
AGENT_POLL_SECONDS = 8 * 60
# The agent only reads Slack and answers, so it needs a fraction of the default 4 CPU / 16 GB box. A backend that
# reserves the whole box bills for all of it.
AGENT_CPU_CORES = 2
AGENT_MEMORY_GB = 4

# Per section, so news from the person's channels always gets room next to what is for them.
MAX_ITEMS_PER_SECTION = 3

PROMPTS_DIR = Path(__file__).parent / "prompts"

# The agent writes these from what it read, so a message in a thread can shape them. They render into Slack mrkdwn,
# so anything that is not a whole id, a channel name or a Slack permalink is dropped.
_CHANNEL_ID = re.compile(r"[CG][A-Z0-9]+")
_USER_ID = re.compile(r"[UW][A-Z0-9_]+")
_CHANNEL_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
_UNSAFE_IN_LINK = re.compile(r"[<>|\s\x00-\x1f\x7f]")
WORKSPACE_HOST_CACHE_SECONDS = 24 * 60 * 60


class AgentSummaryItem(BaseModel):
    text: str
    channel_id: str
    permalink: str | None = None
    # "for_you" mentions, replies to or asks the person; "news" is a thread in their channels they took no part in.
    kind: Literal["for_you", "news"]
    # The flags are required, so the agent states each for every item and the code drops what fails them.
    resolved: bool
    # The person posted or reacted after the newest message, so they have seen it.
    seen_by_person: bool


class AgentSuggestion(BaseModel):
    offer: str
    request: str
    source_permalink: str | None = None
    source_author_id: str | None = None
    source_channel_name: str | None = None
    resolved: bool
    # Anyone, the person included, replied, reacted or took the work.
    has_reaction: bool


class DailyFocusAgentOutput(BaseModel):
    intro: str = ""
    summary: list[AgentSummaryItem] = Field(default_factory=list)
    suggestions: list[AgentSuggestion] = Field(default_factory=list)


def agent_owner_id(integration: WorkspaceIntegration, slack_user_id: str) -> int | None:
    """The PostHog user the run acts as and whose Slack MCP it mounts, when the agent flag is on for them and their
    Slack MCP works. None keeps the person on the pipeline."""
    # The gateway refuses a model outside the billing product's pin, and the run then starts on the default model
    # without a word. Keep the person on the pipeline instead of paying for a model nobody chose.
    if not model_allowed_by_product_pin(DAILY_FOCUS.billing_product, AGENT_MODEL):
        return None
    user = OnboardingContext(integration=integration, slack_user_id=slack_user_id).posthog_user
    if user is None or not is_slack_app_daily_focus_agent_enabled(integration, user.distinct_id):
        return None
    return user.id if _slack_mcp(integration, slack_user_id, user.id) else None


def _slack_mcp(integration: WorkspaceIntegration, slack_user_id: str, owner_id: int) -> str | None:
    # Only the member's Slack MCP for this workspace and this Slack user, so a digest never reads another workspace.
    return slack_mcp_installation_id(
        integration.team_id, owner_id, slack_team_id=integration.integration_id, slack_user_id=slack_user_id
    )


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


def to_work_focus(output: DailyFocusAgentOutput, slack_user_id: str, *, workspace_host: str | None) -> WorkFocus:
    """The agent's answer within the pipeline's limits, whatever the prompt said. A summary item the person already
    saw, and an offer someone already reacted to, are dropped like resolved ones, so the DM holds only what is new to
    the person. So is a link that is not a Slack link, and an offer whose source the person wrote."""
    kept = [
        item
        for item in output.summary
        if not item.resolved
        and not item.seen_by_person
        and item.text.strip()
        and _CHANNEL_ID.fullmatch(item.channel_id)
    ]
    summary = [
        WorkFocusSummaryItem(
            text=item.text.strip()[:MAX_SUMMARY_CHARS],
            channel_id=item.channel_id,
            permalink=_slack_link(item.permalink, workspace_host),
            section=kind,
        )
        for kind in ("for_you", "news")
        for item in [item for item in kept if item.kind == kind][:MAX_ITEMS_PER_SECTION]
    ]
    suggestions = [
        WorkFocusSuggestion(
            offer=item.offer.strip()[:MAX_OFFER_CHARS],
            request=item.request.strip()[:MAX_REQUEST_CHARS],
            source_permalink=_slack_link(item.source_permalink, workspace_host),
            source_author_id=_matching(_USER_ID, item.source_author_id),
            source_channel_name=_matching(_CHANNEL_NAME, (item.source_channel_name or "").lstrip("#")),
        )
        for item in output.suggestions
        if not item.resolved
        and not item.has_reaction
        and item.offer.strip()
        and item.request.strip()
        and item.source_author_id != slack_user_id
    ][:MAX_SUGGESTIONS]
    return WorkFocus(intro=output.intro.strip()[:MAX_INTRO_CHARS], suggestions=suggestions, summary=summary)


def _slack_link(value: str | None, workspace_host: str | None) -> str | None:
    if not value or not workspace_host or _UNSAFE_IN_LINK.search(value):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username or parts.password or port is not None:
        return None
    # The person's own workspace only, so a message cannot have the DM link to a thread in a workspace it chose.
    if parts.hostname != workspace_host or not parts.path.startswith("/archives/"):
        return None
    return value


def workspace_host(integration: WorkspaceIntegration) -> str | None:
    """The host of the workspace's Slack links, such as `example.slack.com`. None when Slack does not answer, which
    drops every link from the DM rather than trusting one."""
    key = f"slack_app:workspace_host:{integration.integration_id}"
    if (cached := cache.get(key)) is not None:
        return cached or None
    try:
        url = SlackIntegration(integration).client.auth_test().get("url") or ""
    except Exception:
        logger.warning("slack_app_workspace_host_failed", integration_id=integration.id, exc_info=True)
        return None
    host = urlsplit(url).hostname or ""
    host = host if host.endswith(".slack.com") else ""
    cache.set(key, host, WORKSPACE_HOST_CACHE_SECONDS)
    return host or None


def _matching(pattern: re.Pattern[str], value: str | None) -> str | None:
    return value if value and pattern.fullmatch(value) else None


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
    installation_id = _slack_mcp(integration, slack_user_id, owner_id)
    if installation_id is None:
        return "agent_unavailable"
    output = asyncio.run(_ask_agent(integration, slack_user_id, owner_id, installation_id, since=since, zone=zone))
    focus = to_work_focus(output, slack_user_id, workspace_host=workspace_host(integration))
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
    prompt = render_prompt(slack_user_id, since=since, zone=zone)
    session, output = await MultiTurnSession.start(
        prompt=prompt,
        context=CustomPromptSandboxContext(
            team_id=integration.team_id,
            user_id=owner_id,
            posthog_mcp_scopes="read_only",
            model=AGENT_MODEL,
            runtime_adapter=AGENT_RUNTIME_ADAPTER,
            # Slack messages steer the run and it has no repository work, so it gets no GitHub credential at all.
            github_access=GithubAccess.NONE,
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


def render_prompt(slack_user_id: str, *, since: datetime, zone: ZoneInfo, threads: str | None = None) -> str:
    """The run's prompt. `threads` puts the Slack threads in the prompt in place of the Slack tools, so the eval
    grades this prompt without a Slack workspace."""
    return _prompt_template().render(
        person=f"<@{slack_user_id}>",
        since=since.astimezone(zone).strftime("%A %H:%M"),
        zone=zone.key,
        max_items_per_section=MAX_ITEMS_PER_SECTION,
        max_suggestions=MAX_SUGGESTIONS,
        threads=threads,
    )


@functools.cache
def _prompt_template() -> Template:
    # StrictUndefined, so a variable the template names and the call forgets fails the run instead of sending blanks.
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR), autoescape=select_autoescape(), undefined=StrictUndefined)
    return env.get_template("daily_focus_agent.jinja")
