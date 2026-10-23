"""The Slack app features that a tip can promote.

Each feature answers two questions about one Slack user: ``is_eligible`` (can this person use
the feature now) and ``was_used`` (does this person already use it). Both read stored state
only, so a user who started before tips existed is judged the same way as a new user.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property
from typing import Literal

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.mcp_store.backend.facade.api import get_active_installations
from products.slack_app.backend.feature_flags import is_slack_app_assistant_enabled
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import personal_integrations_url, project_web_url
from products.subscriptions.backend.facade.api import user_has_slack_subscription


class SlackFeature(StrEnum):
    THREAD_FOLLOWUP = "thread_followup"
    SUBSCRIPTION = "subscription"
    CODE_CHANGE_PR = "code_change_pr"
    MCP_TOOL = "mcp_tool"
    DIRECT_MESSAGE = "direct_message"


@frozen(slots=False)
class TipContext:
    """The Slack user and the thread that a tip is for. Team facts load once, on first use."""

    integration: Integration
    slack_user_id: str
    posthog_user_id: int | None
    channel: str
    settings: SlackSettings

    @property
    def team_id(self) -> int:
        return self.integration.team_id

    @property
    def in_direct_message(self) -> bool:
        # Slack gives every direct message conversation an id that starts with "D".
        return self.channel.startswith("D")

    @cached_property
    def team_has_github(self) -> bool:
        return Integration.objects.filter(team_id=self.team_id, kind="github").exists()


@frozen
class TipCta:
    kind: Literal["url", "action"]
    label: str
    url: str | None = None


class TipFeature:
    feature: SlackFeature
    # Lower comes first when nothing in the message points at one feature.
    rank: int
    text: str
    # What the decision model reads to match a message to this feature.
    choice_criteria: str

    def is_eligible(self, ctx: TipContext) -> bool:
        raise NotImplementedError

    def was_used(self, ctx: TipContext) -> bool:
        raise NotImplementedError

    def cta(self, ctx: TipContext) -> TipCta | None:
        return None


class ThreadFollowupTip(TipFeature):
    feature = SlackFeature.THREAD_FOLLOWUP
    rank = 10
    text = (
        "Tip: in threads you start with me, you can reply without tagging me. "
        "I ask before I pick up the reply, or I can always pick it up."
    )
    choice_criteria = (
        "Replying in a thread without tagging the assistant. Fits a message that continues a conversation "
        "or asks a follow-up question about an earlier answer."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        # In a direct message every reply already goes to PostHog.
        return not ctx.in_direct_message

    def was_used(self, ctx: TipContext) -> bool:
        # Any stored choice means the person found the setting.
        return ctx.settings.untagged_followup_mode is not None

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(kind="action", label="Always pick up my replies")


class SubscriptionTip(TipFeature):
    feature = SlackFeature.SUBSCRIPTION
    rank = 20
    text = (
        "Tip: I can send you a report in Slack on a schedule. "
        "For example: _@PostHog send me our weekly signups every Monday at 9:00_."
    )
    choice_criteria = (
        "Scheduled reports posted to Slack. Fits a message about a number the person checks again and again, "
        "such as weekly signups, a recurring report, or a metric they track over time."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.posthog_user_id is not None

    def was_used(self, ctx: TipContext) -> bool:
        if ctx.posthog_user_id is None:
            return False
        return user_has_slack_subscription(team_id=ctx.team_id, user_id=ctx.posthog_user_id)


class CodeChangePrTip(TipFeature):
    feature = SlackFeature.CODE_CHANGE_PR
    rank = 30
    text = (
        "Tip: I can also change code. Ask me to fix a bug or add an event, and I open a pull request for you to review."
    )
    choice_criteria = (
        "Code changes and pull requests. Fits a message about a bug, an error, an exception, missing tracking, "
        "or anything in the product's source code."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.posthog_user_id is not None and ctx.team_has_github

    def was_used(self, ctx: TipContext) -> bool:
        if ctx.posthog_user_id is None:
            return False
        return UserIntegration.objects.filter(
            user_id=ctx.posthog_user_id, kind=UserIntegration.IntegrationKind.GITHUB
        ).exists()

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(kind="url", label="Connect your GitHub", url=personal_integrations_url(ctx.team_id))


class McpToolTip(TipFeature):
    feature = SlackFeature.MCP_TOOL
    rank = 40
    text = (
        "Tip: I can also use your other tools, such as Linear or Notion. "
        "Connect them in PostHog, and I use them with your own access."
    )
    choice_criteria = (
        "Connecting other work tools such as Linear, Jira, Notion or Google Drive. Fits a message that mentions "
        "tickets, issues, docs, specs or another work tool."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.posthog_user_id is not None

    def was_used(self, ctx: TipContext) -> bool:
        if ctx.posthog_user_id is None:
            return False
        return bool(get_active_installations(ctx.team_id, ctx.posthog_user_id))

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(kind="url", label="Connect a tool", url=f"{project_web_url(ctx.team_id)}/mcp-servers")


class DirectMessageTip(TipFeature):
    feature = SlackFeature.DIRECT_MESSAGE
    rank = 50
    text = "Tip: you can also send me a direct message, for questions you want to keep to yourself."
    choice_criteria = (
        "Private direct messages with the assistant. Fits a message about a sensitive topic, such as one customer, "
        "revenue, salaries, or the person's own work."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return not ctx.in_direct_message and is_slack_app_assistant_enabled(ctx.integration)

    def was_used(self, ctx: TipContext) -> bool:
        return SlackThreadTaskMapping.objects.filter(
            slack_workspace_id=ctx.integration.integration_id,
            mentioning_slack_user_id=ctx.slack_user_id,
            conversation_type=SlackThreadTaskMapping.ConversationType.IM,
        ).exists()

    def cta(self, ctx: TipContext) -> TipCta | None:
        app_id = (ctx.integration.config or {}).get("app_id")
        if not app_id:
            return None
        return TipCta(
            kind="url",
            label="Open a direct message",
            url=f"slack://app?team={ctx.integration.integration_id}&id={app_id}&tab=messages",
        )


CATALOG: dict[SlackFeature, TipFeature] = {
    tip.feature: tip
    for tip in (ThreadFollowupTip(), SubscriptionTip(), CodeChangePrTip(), McpToolTip(), DirectMessageTip())
}
