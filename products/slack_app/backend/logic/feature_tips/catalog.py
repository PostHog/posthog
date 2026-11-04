"""The Slack app features that a tip can promote.

Each feature answers two questions about one Slack user: ``is_eligible`` (can this person use
the feature now) and ``was_used`` (does this person already use it).

``was_used`` reads stored state where the feature leaves some, such as a setting or a connected
account, so a user who started before tips existed is judged the same way as a new user. Some
features leave no state, such as a rating or a fork. The code path of such a feature calls
``record_feature_used`` instead, so their use counts only from the release of tips onward.

``is_eligible`` can make a network call, such as a feature flag check, so the caller runs it
outside any database lock.
"""

from __future__ import annotations

from functools import cached_property

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.models.integration import SlackIntegration
from posthog.models.user_integration import UserIntegration
from posthog.slack.formatting import channel_id_from_target

from products.mcp_store.backend.facade.api import get_active_installations
from products.slack_app.backend.feature_flags import is_slack_app_assistant_enabled, is_slack_app_forking_enabled
from products.slack_app.backend.inbox_channel import (
    _get_team_channel,
    channel_name_from_target,
    ensure_inbox_channel,
    has_inbox_scopes,
    invite_user_to_inbox,
)
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping, UntaggedFollowupMode
from products.slack_app.backend.services.slack_conversations import resolve_conversation_type
from products.slack_app.backend.services.slack_messages import app_home_url, personal_integrations_url, project_web_url
from products.slack_app.backend.services.slack_scopes import SLACK_CANVAS_SCOPE, SLACK_FILE_SCOPE, has_scopes
from products.slack_app.backend.services.slack_settings import (
    set_auto_model_choice,
    set_untagged_followup_mode,
    set_untagged_question_mode,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, workspace_integrations
from products.subscriptions.backend.facade.api import user_has_slack_subscription


@frozen(slots=False)
class TipContext:
    integration: WorkspaceIntegration
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
        return IntegrationManager.github.oauth.exists(self.team_id)

    @cached_property
    def workspace_has_several_projects(self) -> bool:
        # Every PostHog project connected to this Slack workspace has its own Slack integration row.
        return len(workspace_integrations(self.integration.integration_id)) > 1

    @cached_property
    def inbox_channel_target(self) -> str | None:
        if not has_inbox_scopes(self.integration):
            return None
        target = _get_team_channel(self.team_id)
        if target is None:
            return None
        # A tip names the channel and invites the reader, so a private or unknown channel would
        # leak its name or add someone who was not meant to join it.
        return target if _is_public_channel(self.integration, channel_id_from_target(target)) else None

    @cached_property
    def app_home_url(self) -> str | None:
        return app_home_url(self.integration)


def _is_public_channel(integration: WorkspaceIntegration, channel_id: str) -> bool:
    conversation_type = resolve_conversation_type(SlackIntegration(integration), {}, channel_id)
    return conversation_type == SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL


@frozen
class TipCta:
    label: str
    # Without a URL, the button runs ``apply_action``.
    url: str | None = None


def _home_tab_cta(ctx: TipContext) -> TipCta | None:
    if ctx.app_home_url is None:
        return None
    return TipCta(label="Open the Home tab", url=ctx.app_home_url)


class TipFeature:
    feature: SlackFeature
    # Lower comes first when nothing in the message points at one feature.
    rank: int
    emoji: str
    title: str
    text: str
    choice_criteria: str
    has_action: bool = False

    def is_eligible(self, ctx: TipContext) -> bool:
        return True

    def was_used(self, ctx: TipContext) -> bool:
        """``False`` for a feature without stored state. Its code path records use instead."""
        return False

    def render_text(self, ctx: TipContext) -> str:
        return self.text

    def cta(self, ctx: TipContext) -> TipCta | None:
        return None

    def apply_action(self, integration: WorkspaceIntegration, slack_user_id: str) -> str:
        raise NotImplementedError


class ThreadFollowupTip(TipFeature):
    feature = SlackFeature.THREAD_FOLLOWUP
    rank = 10
    has_action = True
    emoji = "💬"
    title = "Reply without tagging me"
    text = "In threads you start with me, you can reply without tagging me. I ask before I pick up the reply, or I can always pick it up."
    choice_criteria = (
        "Replying in a thread without tagging the assistant. Fits a message that continues a conversation "
        'or asks a follow-up question about an earlier answer, such as one that starts with "and" or asks '
        'about "the same numbers", "that chart" or "those users".'
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        # In a direct message every reply already goes to PostHog.
        return not ctx.in_direct_message

    def was_used(self, ctx: TipContext) -> bool:
        # Any stored choice means the person found the setting.
        return ctx.settings.untagged_followup_mode is not None

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(label="Always pick up my replies")

    def apply_action(self, integration: WorkspaceIntegration, slack_user_id: str) -> str:
        set_untagged_followup_mode(integration.integration_id, slack_user_id, UntaggedFollowupMode.AUTO)
        return (
            "✅ Done. I'll pick up your replies in threads you start with me. "
            "You can change this in the PostHog app Home tab."
        )


class SubscriptionTip(TipFeature):
    feature = SlackFeature.SUBSCRIPTION
    rank = 20
    emoji = "📬"
    title = "Get reports on a schedule"
    text = "I can send you a report in Slack on a schedule. For example: _@PostHog send me our weekly signups every Monday at 9:00_."
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
    emoji = "🛠️"
    title = "I can change code too"
    text = "Ask me to fix a bug or add an event, and I open a pull request for you to review."
    choice_criteria = (
        "The person asks to change their product's code: fix a bug or an error, add or change an event or "
        "tracking, or open a pull request."
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
        return TipCta(label="Connect your GitHub", url=personal_integrations_url(ctx.team_id))


class McpToolTip(TipFeature):
    feature = SlackFeature.MCP_TOOL
    rank = 40
    emoji = "🔌"
    title = "Connect MCP servers"
    text = (
        "I can also use MCP servers, such as Linear or Notion. "
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
        return TipCta(label="Connect an MCP server", url=f"{project_web_url(ctx.team_id)}/mcp-servers")


class DirectMessageTip(TipFeature):
    feature = SlackFeature.DIRECT_MESSAGE
    rank = 50
    emoji = "🔒"
    title = "Ask me in private"
    text = "You can also send me a direct message, for questions you want to keep to yourself."
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
        url = app_home_url(ctx.integration, tab="messages")
        if url is None:
            return None
        return TipCta(label="Open a direct message", url=url)


class FileAttachmentsTip(TipFeature):
    feature = SlackFeature.FILE_ATTACHMENTS
    rank = 60
    emoji = "📎"
    title = "Send me screenshots and files"
    text = "Attach a screenshot or a file to your message, and I read it together with your question."
    choice_criteria = (
        "Sending screenshots and files to the assistant. Fits a message that describes something on screen, "
        "a design, a spreadsheet, a log file, or an error the person sees."
    )


class FileOutputsTip(TipFeature):
    feature = SlackFeature.FILE_OUTPUTS
    rank = 70
    emoji = "📊"
    title = "Get files back"
    text = "Ask me for a CSV or a chart, and I add it to the thread as a file."
    choice_criteria = (
        "Files and Slack canvases made by the assistant. Fits a message that asks for an export, a list of rows, "
        "a chart to share, or a long report."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return has_scopes(ctx.integration, {SLACK_FILE_SCOPE})

    def render_text(self, ctx: TipContext) -> str:
        if has_scopes(ctx.integration, {SLACK_CANVAS_SCOPE}):
            return (
                "Ask me for a CSV, a chart, or a long report, and I add it to the thread as a file or a Slack canvas."
            )
        return self.text


class InboxChannelTip(TipFeature):
    feature = SlackFeature.INBOX_CHANNEL
    rank = 80
    has_action = True
    emoji = "📥"
    title = "See what PostHog finds"
    text = "Join the PostHog inbox channel to see the problems that PostHog finds in your product."
    choice_criteria = (
        "A Slack channel with reports about problems PostHog finds on its own, such as new or spiking errors. "
        "Fits a message about errors, regressions, incidents, or keeping watch on the product."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.inbox_channel_target is not None

    def render_text(self, ctx: TipContext) -> str:
        if ctx.inbox_channel_target is None:
            return self.text
        name = channel_name_from_target(ctx.inbox_channel_target)
        return f"Join {name} to see the problems that PostHog finds in your product, such as new errors."

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(label="Join the channel")

    def apply_action(self, integration: WorkspaceIntegration, slack_user_id: str) -> str:
        channel = ensure_inbox_channel(integration)
        # Checked again on click, because the channel can turn private after the tip was shown.
        if channel is None or not _is_public_channel(integration, channel[0]):
            return "I couldn't add you to the channel. Ask a Slack admin to add you."
        if not invite_user_to_inbox(integration, channel[0], slack_user_id):
            return "I couldn't add you to the channel. Try again later, or ask a Slack admin to add you."
        return f"✅ Done. You're in {channel[1]}."


class ProjectInMentionTip(TipFeature):
    feature = SlackFeature.PROJECT_IN_MENTION
    rank = 90
    emoji = "🗂️"
    title = "Pick a project in your message"
    text = "Name a project in your message, and I use it for that request. For example: _@PostHog in the website project, why did signups drop?_"
    choice_criteria = (
        "Naming a PostHog project in one request. Fits a message that names which of several apps, sites or "
        'environments to look in, such as "in the mobile app" or "on staging". A platform used as a filter '
        'or breakdown, such as "for mobile", or a mention of "the app", names no project.'
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.workspace_has_several_projects


class AppHomeProjectTip(TipFeature):
    feature = SlackFeature.APP_HOME_PROJECT
    rank = 100
    emoji = "🏠"
    title = "Choose your default project"
    text = "You can choose your default project in the Home tab of the PostHog app."
    choice_criteria = (
        "Changing the default PostHog project. Fits a message that asks to switch projects, or says the "
        "person usually works in a project other than the one the assistant used."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.workspace_has_several_projects

    def was_used(self, ctx: TipContext) -> bool:
        return ctx.settings.default_integration_id is not None

    def cta(self, ctx: TipContext) -> TipCta | None:
        return _home_tab_cta(ctx)


class ModelInMentionTip(TipFeature):
    feature = SlackFeature.MODEL_IN_MENTION
    rank = 110
    emoji = "🧠"
    title = "Pick a model for one request"
    text = "Name the model in your message. For example: _@PostHog use sonnet and fix the flaky checkout test_."
    choice_criteria = (
        "Choosing an AI model or effort level for one request. Fits a hard or long task, such as a deep "
        "investigation or a large code change, or a message about speed or quality of answers."
    )


class AutoModelChoiceTip(TipFeature):
    feature = SlackFeature.AUTO_MODEL_CHOICE
    rank = 120
    has_action = True
    emoji = "⚡"
    title = "Let me pick the model"
    text = "I can choose the model for each task you start: a faster one for short questions and a stronger one for code changes."
    choice_criteria = (
        "Letting the assistant choose the AI model for each task. Fits a message about answer speed, cost, "
        "or a mix of quick questions and large tasks."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        # Without a linked PostHog user the router cannot run, so the setting would do nothing.
        return ctx.posthog_user_id is not None

    def was_used(self, ctx: TipContext) -> bool:
        return ctx.settings.auto_model_choice is not None

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(label="Turn it on")

    def apply_action(self, integration: WorkspaceIntegration, slack_user_id: str) -> str:
        set_auto_model_choice(integration.integration_id, slack_user_id, True)
        return "✅ Done. I'll choose the model for each new task you start. You can change this in the PostHog app Home tab."


class AppHomeTasksTip(TipFeature):
    feature = SlackFeature.APP_HOME_TASKS
    rank = 130
    emoji = "📋"
    title = "See all your tasks"
    text = "The Home tab of the PostHog app lists your tasks and their status."
    choice_criteria = (
        "A list of the person's tasks and their status. Fits a message that asks about an earlier request, "
        "a pull request in progress, or what the assistant is working on."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return ctx.app_home_url is not None

    def cta(self, ctx: TipContext) -> TipCta | None:
        return _home_tab_cta(ctx)


class InsightUnfurlTip(TipFeature):
    feature = SlackFeature.INSIGHT_UNFURL
    rank = 140
    emoji = "🔗"
    title = "Share insight links"
    text = "Paste a link to a PostHog insight in Slack, and I show a preview of it."
    choice_criteria = (
        "Previews of PostHog links pasted in Slack. Fits a message that shares or mentions an insight, "
        "a dashboard, or a chart with the team."
    )


class ForkThreadTip(TipFeature):
    feature = SlackFeature.FORK_THREAD
    rank = 150
    emoji = "🍴"
    title = "Continue in private"
    text = 'To continue a thread in private, use "Fork to DM" in the menu on my answer.'
    choice_criteria = (
        "Moving a channel conversation into a private direct message. Fits a message in a busy channel, "
        "or about a topic the person wants to explore alone."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return not ctx.in_direct_message and is_slack_app_forking_enabled(ctx.integration)


class UnpromptedAnswersTip(TipFeature):
    feature = SlackFeature.UNPROMPTED_ANSWERS
    rank = 160
    has_action = True
    emoji = "🙋"
    title = "Ask without tagging me"
    text = "When you ask about PostHog in a channel without tagging me, I can offer to answer."
    choice_criteria = (
        "Answers to channel questions that do not tag the assistant. Fits a message that the person could "
        "have asked the whole channel, such as a quick data question."
    )

    def is_eligible(self, ctx: TipContext) -> bool:
        return not ctx.in_direct_message

    def was_used(self, ctx: TipContext) -> bool:
        return ctx.settings.untagged_question_mode is not None

    def cta(self, ctx: TipContext) -> TipCta | None:
        return TipCta(label="Always answer my questions")

    def apply_action(self, integration: WorkspaceIntegration, slack_user_id: str) -> str:
        set_untagged_question_mode(integration.integration_id, slack_user_id, UntaggedFollowupMode.AUTO)
        return (
            "✅ Done. I'll answer your questions about PostHog in channels, also when you don't tag me. "
            "You can change this in the PostHog app Home tab."
        )


class AnswerRatingTip(TipFeature):
    feature = SlackFeature.ANSWER_RATING
    rank = 170
    emoji = "👍"
    title = "Rate my answers"
    text = "Use the 👍 and 👎 buttons under my answers. This helps us make them better."
    choice_criteria = (
        "Rating the assistant's answers. Fits a message that says an earlier answer was wrong, "
        "incomplete, or very helpful."
    )


class ReplySuggestionsTip(TipFeature):
    feature = SlackFeature.REPLY_SUGGESTIONS
    rank = 180
    emoji = "👆"
    title = "Ask the next question in one click"
    text = "Click a suggested reply under my answer to ask your next question."
    choice_criteria = (
        "Suggested follow-up replies under an answer. Fits a short follow-up question that continues an earlier answer."
    )


CATALOG: dict[SlackFeature, TipFeature] = {
    tip.feature: tip
    for tip in (
        ThreadFollowupTip(),
        SubscriptionTip(),
        CodeChangePrTip(),
        McpToolTip(),
        DirectMessageTip(),
        FileAttachmentsTip(),
        FileOutputsTip(),
        InboxChannelTip(),
        ProjectInMentionTip(),
        AppHomeProjectTip(),
        ModelInMentionTip(),
        AutoModelChoiceTip(),
        AppHomeTasksTip(),
        InsightUnfurlTip(),
        ForkThreadTip(),
        UnpromptedAnswersTip(),
        AnswerRatingTip(),
        ReplySuggestionsTip(),
    )
}
