"""Suggests first tasks from the recent Slack messages that mention the person, once, after they link their account.

Slack's search terms forbid storing or copying what `assistant.search.context` returns. So the messages stay in
this process: one call searches, has Jev pick the messages that hold work, and has a model write the suggestions.
Only the suggestions and their links leave it.
"""

import re
import json
import asyncio
from collections.abc import Iterable
from dataclasses import field, replace
from datetime import datetime, timedelta
from itertools import islice
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from slack_sdk.errors import SlackApiError, SlackClientError

from posthog.dataclasses import frozen
from posthog.egress.slack.client import SlackWebClient
from posthog.llm.gateway_client import build_ai_gateway_openai_client
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.llm.system_one import NoulAnswer, NoulQuestion
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, build_system_one_client
from posthog.models.integration import SlackIntegration
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.token_bucket import BucketDecision, Budget, consume, refund

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_daily_work_focus_enabled
from products.slack_app.backend.logic.daily_focus import (
    daily_focus_footer_block,
    mark_daily_focus_sending,
    person_zone,
    previous_run_before,
    reschedule_daily_focus,
    resolve_daily_focus,
    turn_on_daily_focus,
)
from products.slack_app.backend.logic.onboarding.actions import WORK_FOCUS_START_ACTION_ID, WORK_FOCUS_TASK_ACTION_ID
from products.slack_app.backend.logic.onboarding.checks import has_ai_approval, out_of_ai_credits
from products.slack_app.backend.logic.onboarding.daily_summary import (
    SummaryThread,
    parallel_map,
    read_thread,
    summary_threads,
    tagged_users,
    thread_text,
)
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, read_action_value
from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.slack_user_info import (
    SLACK_USER_PROFILE_TTL,
    get_cached_bot_user_id,
    get_slack_user_info,
)
from products.slack_app.backend.services.slack_user_oauth import (
    LinkedUserToken,
    linked_posthog_distinct_id,
    linked_search_token,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# pinned: analytics event names, renaming breaks dashboards
SUGGESTIONS_SENT_EVENT = "slack app work focus suggestions sent"
SUGGESTION_CLICKED_EVENT = "slack app work focus suggestion clicked"
SUGGESTION_STARTED_EVENT = "slack app work focus suggestion started"
WORK_FOCUS_SUGGESTION_BLOCK_PREFIX = "work_focus_suggestion_"

# Slack returns at most 20 results a page and allows a person about 10 search calls a minute. Three pages stay at
# three calls, the most one person's run may take.
SEARCH_LIMIT = 20
SEARCH_PAGES = 3
# A workspace gets about 10 search calls a minute, so a burst of links waits for tokens.
SEARCH_BUDGET = Budget(burst=10, per_hour=600)
# A daily run reads one workday, so one page is enough.
DAILY_SEARCH_PAGES = 1
DAILY_SEARCH_CALLS = DAILY_SEARCH_PAGES
# Daily runs in one workspace start this far apart, so together they stay within its search budget.
DAILY_RUN_SPACING_SECONDS = 3600 * DAILY_SEARCH_CALLS // SEARCH_BUDGET.per_hour
MAX_MESSAGE_CHARS = 500
# users.info does not mark Slackbot with is_bot, but a person who tags Slackbot hands it the work like any other app.
SLACKBOT_USER_ID = "USLACKBOT"
# Message text decides which users are looked up, so anyone in a channel could otherwise make a run call users.info
# for hundreds of made-up ids. The workspace shares that Slack limit with every other Slack app feature.
MAX_BOT_LOOKUPS = 25
BOT_LOOKUP_BUDGET = Budget(burst=MAX_BOT_LOOKUPS, per_hour=1800)
# The same text decides the size of the cache query, so it reads at most this many users at a time.
MAX_PRIMED_USERS = 200

# The model calls spend the team's PostHog AI credits, the same as the other Slack app calls.
WORK_FOCUS_AI_PRODUCT = "slack_app"
# Every Slack app call shares the product, so the captured generation carries this property to say which run made it.
WORK_FOCUS_FLOW_PROPERTY = "slack_app_flow"
WorkFocusFlow = Literal["slack_app_onboarding", "slack_app_daily_focus"]
# pinned: analytics property values, renaming breaks dashboards
_FLOW_MODES: dict[WorkFocusFlow, str] = {"slack_app_onboarding": "onboarding", "slack_app_daily_focus": "daily"}
# Jev ranks the messages, because a judgment costs far less than generated text, and only the few messages it keeps
# reach the model that writes. One question for each message, and a request takes 32 questions at most.
ONBOARDING_PRIVACY_LINE = "I read your recent messages once and kept nothing. Each one starts its own thread."

RANK_MODEL = DEFAULT_DECISION_MODEL
RANK_BATCH_SIZE = GATEWAY_MAX_QUESTIONS
RANK_MIN_PROBABILITY = 0.5
RANK_TIMEOUT_SECONDS = 15.0
MAX_CANDIDATES = 5
RANK_INSTRUCTIONS = (
    "`person` is the person the digest is for. `messages` holds Slack messages from other people that mention them. "
    "For the message this question names, "
    "decide whether it describes work that PostHog could do for this person now: answer a product data question, "
    "investigate a bug or an error, or change code in a connected repository."
)
RANK_TRUE = "The message asks for, reports or plans work of that kind."
RANK_FALSE = (
    "The message is chat, a greeting, a status note, work someone handed to PostHog, another AI agent or another app, "
    "or work that PostHog cannot help with."
)
RESOLVE_MIN_PROBABILITY = 0.5
RESOLVE_INSTRUCTIONS = (
    "`person` is the person the digest is for. `threads` holds Slack threads in which someone asked them for, reported or planned some work. For the thread this "
    "question names, decide whether that work is still open."
)
RESOLVE_TRUE = "Nobody answered, or the thread still asks for the work."
RESOLVE_FALSE = (
    "The thread answered it, says it is done, fixed or merged, a pull request is open for it, or someone handed it to "
    "an AI agent or another app."
)

WRITE_MODEL = "gpt-6-luna"
WRITE_TIMEOUT_SECONDS = 30.0
WRITE_MAX_COMPLETION_TOKENS = 2048
MAX_SUGGESTIONS = 3
MAX_SUMMARY_ITEMS = 5
MAX_SUMMARY_CHARS = 120
MAX_INTRO_CHARS = 140
MAX_OFFER_CHARS = 110
MAX_REQUEST_CHARS = 500

_CHANNEL_TYPE_SCOPES = {
    "public_channel": "search:read.public",
    "private_channel": "search:read.private",
    "im": "search:read.im",
    "mpim": "search:read.mpim",
}

WRITE_INSTRUCTIONS = """You write a short, friendly direct message from PostHog to one person in Slack. PostHog is an \
AI agent that answers questions from product data (analytics, session replay, errors, feature flags, experiments) and \
opens pull requests in connected repositories. The numbered messages are recent Slack messages from other people that \
mention the person. The numbered threads, when given, are threads from the channels they are in that moved since \
their last digest, and a thread marked "you are in this thread" is one they took part in. <person> names the \
person the message goes to, with their Slack token and name. Write to them as "you" and never refer to them by \
their token or their name.

Return:
- "intro": one short, warm sentence to the person that leads into the items below it. When there are summary \
items, name only what those items cover, such as "👀 Since yesterday: pricing calls, a workflows check and two database fixes." \
When there are none, lead into the suggestions, such as "👀 A couple of asks for you came in." Never call the items \
the person's own work unless the person did them. Start it with one fitting emoji. At most 120 characters.
- "suggestions": at most 3 tasks that PostHog could do for them, the most useful first. Each task has:
  - "offer": one short line in the second person that ends with a question. At most 100 characters. For example: \
"Chart previews ignore edited query params. Want me to find out why?"
  - "request": the full task, written as the person would ask PostHog, such as "Find out why chart link previews \
ignore edited query parameters, and open a pull request with the fix." At most 500 characters.
  - "source": the number of the message the task comes from.
- "summary": at most 5 one-line items on what happened in the threads, the ones the person is in first, then the \
most consequential. Each item has:
  - "text": one plain sentence of at most 110 characters that starts with who did it and says what was decided, \
reported, launched or asked. When the person did it, start with "You". Credit work to whoever did it: when a \
thread says an AI agent such as Claude found or wrote something, say the agent did, not the person. Refer to people only with the `<@U…>` tokens exactly as they appear, which Slack \
shows as names. Do not name the channel; it is added after the sentence.
  - "source": the number of the thread the item comes from.
  Write one item for every thread, up to 5, and do not choose a subset: the threads were already picked for this \
person. Leave out only a thread that is just chat, a thread that is just a \
status note such as someone being heads down, and a thread that already became a suggestion. An open problem, a \
blocker or a request is never just a status note, even when its latest message is a status update. Return an empty \
list when no threads are given.

Keep it short and friendly, with no other emoji and no em dashes. Never quote a message, never write a person's name, \
and never copy private details. Never offer work that someone handed to PostHog, another AI agent or another app, or \
that a thread already answered. Suggest nothing when no message shows work that PostHog can help with."""

_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "slack_app_work_focus",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "intro": {"type": "string"},
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "offer": {"type": "string"},
                            "request": {"type": "string"},
                            "source": {"type": "integer"},
                        },
                        "required": ["offer", "request", "source"],
                        "additionalProperties": False,
                    },
                },
                "summary": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}, "source": {"type": "integer"}},
                        "required": ["text", "source"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["intro", "suggestions", "summary"],
            "additionalProperties": False,
        },
    },
}


class WorkFocusTransientError(Exception):
    """Raised before anything is sent, so the activity retries and no outcome is stored."""


class WorkFocusRateLimited(Exception):
    """Raised before anything is sent, so the activity can retry later."""


@frozen
class FoundMessage:
    content: str
    channel_id: str
    # The root of the thread the message is in, which the search only names in the permalink; its own ts otherwise.
    thread_ts: str
    channel_name: str | None
    permalink: str | None
    author_id: str | None
    # Read from the full message, because the content is cut to MAX_MESSAGE_CHARS.
    tagged: tuple[str, ...] = ()
    # The thread read in full, when the bot could read it and it holds more than the message.
    thread: str | None = None


@frozen
class DigestPerson:
    slack_user_id: str
    name: str | None

    def as_state(self) -> dict[str, str]:
        return {"slack_user_id": self.slack_user_id, "name": self.name or ""}

    @property
    def line(self) -> str:
        return f"<@{self.slack_user_id}>" + (f" ({self.name})" if self.name else "")


@frozen
class WorkFocusSuggestion:
    offer: str
    request: str
    source_permalink: str | None = None
    source_author_id: str | None = None
    source_channel_name: str | None = None


@frozen
class WorkFocusSummaryItem:
    text: str
    channel_id: str
    permalink: str | None


@frozen
class WorkFocus:
    intro: str
    suggestions: list[WorkFocusSuggestion]
    summary: list[WorkFocusSummaryItem] = field(default_factory=list)


def find_and_send_work_focus(integration: WorkspaceIntegration, slack_user_id: str) -> str:
    """Returns the outcome, which is also stored, so the work focus never runs twice for a person."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is not None and state.work_focus_at:
        return "already_done"
    # Not stored either: a run queued before the flag went off sends nothing, and a later trigger can still run it.
    if not _daily_work_focus_on(integration, slack_user_id):
        return "flag_off"
    # Not stored, so the work focus can still run once the person can reach the project, and the organization allows
    # AI data processing and has credits.
    if blocked := _blocked_reason(integration, slack_user_id):
        return blocked
    outcome = _find_and_send(integration, slack_user_id)
    update_onboarding(slack_workspace_id, slack_user_id, work_focus_outcome=outcome)
    return outcome


def find_and_send_daily_focus(
    integration: WorkspaceIntegration, slack_user_id: str, *, since: datetime, run_at: datetime
) -> str:
    """One workday's work focus, from the messages sent after ``since``, for the run the sweep claimed at ``run_at``.
    A quiet day sends nothing. The free checks come first, so a run that cannot send spends no queries, Slack calls
    or credits."""
    if not _daily_work_focus_on(integration, slack_user_id):
        return "flag_off"
    daily = resolve_daily_focus(integration.integration_id, slack_user_id)
    if not daily.enabled:
        return "turned_off"
    # A retry that a later sweep overtook: that sweep's run sends its own day.
    if daily.last_run_at != run_at:
        return "superseded"
    if daily.already_sent:
        return "already_sent"
    token = _search_token(integration, slack_user_id)
    if token is None:
        return "no_search_scope"
    # A task started from the DM reads its thread with the bot, so suggestions need the bot's DM scope.
    if SlackIntegration(integration).missing_scopes(frozenset({"im:history"})):
        return "missing_bot_scope"
    if blocked := _blocked_reason(integration, slack_user_id):
        return blocked
    zone = person_zone(integration, slack_user_id)
    reschedule_daily_focus(integration, slack_user_id, zone)
    found = _find(
        integration, slack_user_id, token, after=since, pages=DAILY_SEARCH_PAGES, flow="slack_app_daily_focus"
    )
    if isinstance(found, str):
        return found
    blocks = [
        *work_focus_blocks(
            integration,
            found.focus,
            slack_user_id,
            privacy=_privacy_line(channels=found.thread_count > 0, since=_since_label(since, zone)),
        ),
        daily_focus_footer_block(integration, daily.at, zone, first=False),
    ]
    # Claimed before the DM goes out. When Slack takes the DM but the response times out, the retry sends nothing.
    if not mark_daily_focus_sending(integration, slack_user_id, run_at):
        return "already_sent"
    return _post(integration, slack_user_id, found, blocks)


def _daily_work_focus_on(integration: WorkspaceIntegration, slack_user_id: str) -> bool:
    return is_slack_app_daily_work_focus_enabled(
        integration, linked_posthog_distinct_id(slack_user_id=slack_user_id, slack_team_id=integration.integration_id)
    )


def _search_token(integration: WorkspaceIntegration, slack_user_id: str) -> LinkedUserToken | None:
    return linked_search_token(slack_user_id=slack_user_id, slack_team_id=integration.integration_id)


def _blocked_reason(integration: WorkspaceIntegration, slack_user_id: str) -> str | None:
    """Why a work focus must not spend the project's AI credits now, or None. An organization member can link their
    Slack account without access to this project, and a Slack link outlives an organization membership."""
    if not OnboardingContext(integration=integration, slack_user_id=slack_user_id).has_project_access:
        return "no_project_access"
    if not has_ai_approval(integration.team_id):
        return "no_ai_consent"
    if out_of_ai_credits(integration.team_id):
        return "out_of_ai_credits"
    return None


def _ready_to_send(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    # Stored before the DM goes out. When Slack takes the DM but the response times out, the retry sees this and
    # sends nothing, because a second DM would carry a second set of buttons.
    update_onboarding(integration.integration_id, slack_user_id, work_focus_outcome="sending")


def _daily_focus_footer(integration: WorkspaceIntegration, slack_user_id: str) -> dict | None:
    """The onboarding turns the daily work focus on, unless the person already chose. The footer shows while it is
    on."""
    if not _daily_work_focus_on(integration, slack_user_id):
        return None
    daily = resolve_daily_focus(integration.integration_id, slack_user_id)
    if daily.enabled is None:
        zone = turn_on_daily_focus(integration, slack_user_id, source="onboarding")
    elif daily.enabled:
        zone = person_zone(integration, slack_user_id)
    else:
        return None
    return daily_focus_footer_block(integration, daily.at, zone, first=True)


def _find_and_send(integration: WorkspaceIntegration, slack_user_id: str) -> str:
    token = _search_token(integration, slack_user_id)
    if token is None:
        return "no_search_scope"
    found = _find(
        integration,
        slack_user_id,
        token,
        after=_previous_workday(integration, slack_user_id),
        flow="slack_app_onboarding",
    )
    # Turned on before the quiet outcomes return and before the DM, so a retry after a failed write still finds it on.
    footer = _daily_focus_footer(integration, slack_user_id)
    if isinstance(found, str):
        return found
    blocks = work_focus_blocks(
        integration, found.focus, slack_user_id, privacy=_privacy_line(channels=found.thread_count > 0, since=None)
    )
    if footer is not None:
        blocks.append(footer)
    _ready_to_send(integration, slack_user_id)
    return _post(integration, slack_user_id, found, blocks)


@frozen
class _Found:
    focus: WorkFocus
    message_count: int
    candidate_count: int
    thread_count: int
    # Counts the person's own messages too.
    handed_off_count: int
    flow: WorkFocusFlow


def _find(
    integration: WorkspaceIntegration,
    slack_user_id: str,
    token: LinkedUserToken,
    *,
    after: datetime,
    flow: WorkFocusFlow,
    pages: int = SEARCH_PAGES,
) -> _Found | str:
    """The suggestions from the messages sent after ``after``, and the summary of the threads that moved since then,
    or the outcome that stops the run. Threads alone are enough to write, so a quiet inbox still gets the news from
    its channels."""
    channel_types = [kind for kind, scope in _CHANNEL_TYPE_SCOPES.items() if scope in token.scopes]
    person = _person(integration, slack_user_id)
    messages = _search_messages(integration, token.access_token, slack_user_id, channel_types, after=after, pages=pages)
    if messages is None:
        raise WorkFocusTransientError("search failed")
    bot_user_id = get_cached_bot_user_id(SlackIntegration(integration), integration)
    if not bot_user_id:
        logger.warning("slack_app_work_focus_bot_user_unknown", integration_id=integration.id)
    bots = _BotLookup(integration, bot_user_id)
    found_count = len(messages)
    messages = [message for message in messages if message.author_id != slack_user_id]
    bots.prime(user for message in messages for user in message.tagged)
    messages = [message for message in messages if not any(bots.is_bot(user) for user in message.tagged)]
    handed_off_count = found_count - len(messages)
    # Read after the search, so a search that is rate limited retries without reading the channels again.
    threads = summary_threads(integration, slack_user_id, since=after, bot_user_id=bot_user_id)
    candidates: list[FoundMessage] = []
    if messages:
        try:
            candidates, handed_off_threads = _still_open(
                integration,
                rank_messages(integration.team_id, messages, flow=flow, person=person),
                flow=flow,
                bot_user_id=bot_user_id,
                bots=bots,
                person=person,
                known={(thread.channel_id, thread.ts): thread for thread in threads},
            )
            handed_off_count += handed_off_threads
        except Exception as error:
            logger.warning("slack_app_work_focus_rank_failed", exc_info=True)
            raise WorkFocusTransientError("rank failed") from error
    if not candidates and not threads:
        return "nothing_actionable" if messages else "not_enough_messages"
    try:
        focus = write_work_focus(integration.team_id, candidates, flow=flow, threads=threads, person=person)
    except Exception as error:
        logger.warning("slack_app_work_focus_model_failed", exc_info=True)
        raise WorkFocusTransientError("write failed") from error
    if not focus.suggestions and not focus.summary:
        return "no_suggestions"
    return _Found(
        focus=focus,
        message_count=len(messages),
        candidate_count=len(candidates),
        thread_count=len(threads),
        handed_off_count=handed_off_count,
        flow=flow,
    )


def _post(integration: WorkspaceIntegration, slack_user_id: str, found: _Found, blocks: list[dict]) -> str:
    try:
        SlackIntegration(integration).client.chat_postMessage(
            channel=slack_user_id,
            text=_safe_mrkdwn(found.focus.intro),
            blocks=blocks,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError:
        logger.warning("slack_app_work_focus_post_failed", exc_info=True)
        return "post_failed"
    capture_slack_event(
        integration,
        SUGGESTIONS_SENT_EVENT,
        slack_user_id=slack_user_id,
        suggestion_count=len(found.focus.suggestions),
        summary_count=len(found.focus.summary),
        message_count=found.message_count,
        candidate_count=found.candidate_count,
        handed_off_count=found.handed_off_count,
        mode=_FLOW_MODES[found.flow],
    )
    return "sent"


def _since_label(since: datetime, zone: ZoneInfo) -> str:
    since_day = since.astimezone(zone).date()
    today = timezone.now().astimezone(zone).date()
    return "yesterday" if since_day == today - timedelta(days=1) else since_day.strftime("%A")


def _privacy_line(*, channels: bool, since: str | None) -> str:
    """The note under the DM. ``since`` names the day a daily run read back to; the first run reads once."""
    what = "your recent messages" if since is None else "your messages"
    if channels:
        what += " and the channels we share"
    when = "once" if since is None else f"since {since}"
    return f"I read {what} {when} and kept nothing. Each one starts its own thread."


def _previous_workday(integration: WorkspaceIntegration, slack_user_id: str) -> datetime:
    """The same time on the previous workday in the person's timezone, so a Monday run reads back to Friday."""
    now = timezone.now()
    zone = person_zone(integration, slack_user_id)
    return previous_run_before(now, zone, now.astimezone(zone).time())


def _person(integration: WorkspaceIntegration, slack_user_id: str) -> DigestPerson:
    """Who the digest is for, so the models can tell the person's own messages from everyone else's. The name comes
    from the cached Slack profile; without one, the token alone still tells them apart."""
    try:
        user = get_slack_user_info(SlackIntegration(integration), integration, slack_user_id).get("user") or {}
        profile = user.get("profile") or {} if isinstance(user, dict) else {}
        name = str(profile.get("display_name") or profile.get("real_name") or "").strip() or None
    except Exception:
        logger.warning("slack_app_work_focus_person_failed", integration_id=integration.id, exc_info=True)
        name = None
    return DigestPerson(slack_user_id=slack_user_id, name=name)


def _jev_client(team_id: int, *, flow: WorkFocusFlow, classifier: str) -> Any:
    # No TypeSafe fallback: the messages are customer text, and TypeSafe is a third party.
    return build_system_one_client(
        model=RANK_MODEL,
        ai_product=WORK_FOCUS_AI_PRODUCT,
        team_id=team_id,
        properties={"slack_app_classifier": classifier, WORK_FOCUS_FLOW_PROPERTY: flow},
        timeout=RANK_TIMEOUT_SECONDS,
        privacy_mode=True,
    )


def _thread_ts_in(permalink: object) -> str | None:
    if not isinstance(permalink, str):
        return None
    values = parse_qs(urlsplit(permalink).query).get("thread_ts") or []
    return values[0] if values and values[0] else None


class _BotLookup:
    """Whether a Slack user is an app, such as PostHog or another AI agent. Slack marks every app user with is_bot,
    so no list of agent names goes stale. An unknown user answers False, so a failed lookup never hides work: at worst
    the DM offers work that someone already handed to an agent. That is why a rate limit stops the lookups instead of
    retrying the run, which would spend the searches and AI credits again."""

    def __init__(self, integration: WorkspaceIntegration, bot_user_id: str | None) -> None:
        self._integration = integration
        self._slack = SlackIntegration(integration)
        self._known: dict[str, bool] = {user: True for user in (bot_user_id, SLACKBOT_USER_ID) if user}
        self._lookups_left = MAX_BOT_LOOKUPS

    def prime(self, users: Iterable[str]) -> None:
        """Reads the fresh cached profiles in one query, so only the users the cache lacks cost a Slack call."""
        wanted = list(islice(dict.fromkeys(user for user in users if user not in self._known), MAX_PRIMED_USERS))
        if not wanted:
            return
        cached = SlackUserProfileCache.objects.filter(
            integration_id=self._integration.id,
            slack_user_id__in=wanted,
            refreshed_at__gt=timezone.now() - SLACK_USER_PROFILE_TTL,
        ).values_list("slack_user_id", "is_bot")
        self._known.update(cached)

    def is_bot(self, user_id: str) -> bool:
        if user_id in self._known:
            return self._known[user_id]
        # Not stored once the lookups are spent, so made-up mentions cannot grow the dict.
        if self._lookups_left <= 0:
            return False
        self._known[user_id] = self._look_up(user_id)
        return self._known[user_id]

    def _look_up(self, user_id: str) -> bool:
        if self._lookups_left <= 0:
            return False
        decision = consume(f"slack_app:work_focus_bot_lookup:{self._integration.integration_id}", BOT_LOOKUP_BUDGET)
        if isinstance(decision, BucketDecision) and not decision.allowed:
            self._stop("budget_spent")
            return False
        self._lookups_left -= 1
        try:
            user = get_slack_user_info(self._slack, self._integration, user_id).get("user")
        except SlackApiError as error:
            if (error.response or {}).get("error") == "ratelimited":
                self._stop("ratelimited")
            return False
        except (SlackClientError, OSError):
            logger.warning("slack_app_work_focus_bot_lookup_failed", integration_id=self._integration.id, exc_info=True)
            return False
        return isinstance(user, dict) and bool(user.get("is_bot"))

    def _stop(self, reason: str) -> None:
        self._lookups_left = 0
        logger.info("slack_app_work_focus_bot_lookups_stopped", reason=reason, integration_id=self._integration.id)


@frozen
class _CandidateThread:
    text: str | None = None
    app_replied: bool = False
    tagged: tuple[str, ...] = ()


def _still_open(
    integration: WorkspaceIntegration,
    candidates: list[FoundMessage],
    *,
    flow: WorkFocusFlow,
    bot_user_id: str | None,
    bots: _BotLookup,
    person: DigestPerson,
    known: dict[tuple[str, str], SummaryThread],
) -> tuple[list[FoundMessage], int]:
    """The candidates whose work the thread has not finished, and how many were handed to an app. A thread the app
    already replied in, or where a person tagged any app, such as another AI agent, is handled. Jev reads the rest of
    the threads the bot can read; a thread the bot cannot read, or a message with no replies, keeps its candidate. A
    thread the summary already read is not read again."""
    slack = SlackIntegration(integration)

    def thread_of(candidate: FoundMessage) -> _CandidateThread:
        if (summary := known.get((candidate.channel_id, candidate.thread_ts))) is not None:
            return _CandidateThread(text=summary.text, tagged=summary.tagged)
        read = read_thread(slack.client, candidate.channel_id, candidate.thread_ts, bot_user_id=bot_user_id)
        if read is None:
            return _CandidateThread()
        return _CandidateThread(
            # A lone root is the message itself, which Jev already read.
            text=thread_text(read.messages) if len(read.messages) > 1 else None,
            app_replied=read.app_took_part,
            tagged=tagged_users(str(message.get("text") or "") for message in read.messages),
        )

    threads = parallel_map(thread_of, candidates)
    read: list[FoundMessage] = []
    handed_off = 0
    # The bot lookups run here, not in the reader threads, because they read the profile cache from the database.
    bots.prime(user for thread in threads for user in thread.tagged)
    for candidate, thread in zip(candidates, threads):
        if thread.app_replied or any(bots.is_bot(user) for user in thread.tagged):
            handed_off += 1
        else:
            read.append(replace(candidate, thread=thread.text))
    return drop_finished(integration.team_id, read, flow=flow, person=person), handed_off


def drop_finished(
    team_id: int, candidates: list[FoundMessage], *, flow: WorkFocusFlow, person: DigestPerson
) -> list[FoundMessage]:
    """The candidates whose thread Jev reads as still open. A candidate without a thread keeps its place."""
    keys = {f"t{index}": index for index, candidate in enumerate(candidates) if candidate.thread}
    if not keys:
        return candidates
    client = _jev_client(team_id, flow=flow, classifier="work_focus_still_open")
    result = client.decide(
        state={"person": person.as_state(), "threads": {key: candidates[index].thread for key, index in keys.items()}},
        questions={
            key: NoulQuestion(
                instructions=f"{RESOLVE_INSTRUCTIONS} This question names `threads.{key}`.",
                criteria_true=RESOLVE_TRUE,
                criteria_false=RESOLVE_FALSE,
            )
            for key in keys
        },
    )
    finished = {
        keys[key]
        for key, answer in result.answers.items()
        if key in keys and isinstance(answer, NoulAnswer) and answer.probability < RESOLVE_MIN_PROBABILITY
    }
    return [candidate for index, candidate in enumerate(candidates) if index not in finished]


def _search_messages(
    integration: WorkspaceIntegration,
    access_token: str,
    slack_user_id: str,
    channel_types: list[str],
    *,
    after: datetime,
    pages: int,
) -> list[FoundMessage] | None:
    client = SlackWebClient(
        access_token, source="slack_app_work_focus", workspace_id=integration.integration_id, app_id="posthog"
    )
    found: dict[tuple[str, str], FoundMessage] = {}
    # All calls are reserved at once, so two runs cannot each take one call and both fail on the next one.
    bucket = f"slack_app:work_focus_search:{integration.integration_id}"
    cost = pages
    decision = consume(bucket, SEARCH_BUDGET, cost=cost)
    if isinstance(decision, BucketDecision) and not decision.allowed:
        raise WorkFocusRateLimited
    # Only the messages that mention the person. Their own messages hold work they already know about or already
    # handed to an app.
    query = f"<@{slack_user_id}>"
    calls = 0
    try:
        cursor = ""
        for _ in range(pages):
            params: dict[str, Any] = {
                "query": query,
                "channel_types": ",".join(channel_types),
                "content_types": "messages",
                "sort": "timestamp",
                "after": int(after.timestamp()),
                "limit": SEARCH_LIMIT,
                "include_bots": False,
            }
            if cursor:
                params["cursor"] = cursor
            calls += 1
            try:
                response = client.api_call("assistant.search.context", params=params)
            except SlackApiError as error:
                if (error.response or {}).get("error") == "ratelimited":
                    raise WorkFocusRateLimited from error
                logger.warning("slack_app_work_focus_search_failed", error=(error.response or {}).get("error"))
                return None
            except (SlackClientError, OSError):
                logger.warning("slack_app_work_focus_search_failed", exc_info=True)
                return None
            for message in ((response.get("results") or {}).get("messages")) or []:
                _collect(found, message)
            cursor = str((response.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                break
    finally:
        if calls < cost:
            refund(bucket, SEARCH_BUDGET, cost - calls)
    return list(found.values())


def _collect(found: dict[tuple[str, str], FoundMessage], message: dict[str, Any]) -> None:
    content = str(message.get("content") or "").strip()
    key = (str(message.get("channel_id") or ""), str(message.get("message_ts") or ""))
    if not content or message.get("is_author_bot") or key in found:
        return
    channel_name = message.get("channel_name")
    permalink = message.get("permalink")
    author_id = message.get("author_user_id")
    found[key] = FoundMessage(
        content=content[:MAX_MESSAGE_CHARS],
        channel_id=key[0],
        thread_ts=_thread_ts_in(permalink) or key[1],
        # A DM has no channel name worth showing, so only channels keep theirs.
        channel_name=channel_name
        if isinstance(channel_name, str) and channel_name and key[0][:1] in ("C", "G")
        else None,
        author_id=author_id if isinstance(author_id, str) and author_id else None,
        permalink=permalink if isinstance(permalink, str) and permalink.startswith("https://") else None,
        tagged=tagged_users([content]),
    )


def rank_messages(
    team_id: int, messages: list[FoundMessage], *, flow: WorkFocusFlow, person: DigestPerson
) -> list[FoundMessage]:
    """The messages most likely to hold work for PostHog, most likely first."""
    client = _jev_client(team_id, flow=flow, classifier="work_focus_rank")
    scored: list[tuple[float, int]] = []
    for batch_start in range(0, len(messages), RANK_BATCH_SIZE):
        batch = messages[batch_start : batch_start + RANK_BATCH_SIZE]
        keys = [f"m{batch_start + offset}" for offset in range(len(batch))]
        result = client.decide(
            state={
                "person": person.as_state(),
                "messages": {key: message.content for key, message in zip(keys, batch)},
            },
            questions={
                key: NoulQuestion(
                    instructions=f"{RANK_INSTRUCTIONS} This question names `messages.{key}`.",
                    criteria_true=RANK_TRUE,
                    criteria_false=RANK_FALSE,
                )
                for key in keys
            },
        )
        for key, index in zip(keys, range(batch_start, batch_start + len(batch))):
            answer = result.answers.get(key)
            if isinstance(answer, NoulAnswer) and answer.probability >= RANK_MIN_PROBABILITY:
                scored.append((answer.probability, index))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [messages[index] for _, index in scored[:MAX_CANDIDATES]]


def write_work_focus(
    team_id: int,
    candidates: list[FoundMessage],
    *,
    flow: WorkFocusFlow,
    threads: list[SummaryThread],
    person: DigestPerson,
) -> WorkFocus:
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=WORK_FOCUS_AI_PRODUCT,
        properties={
            "slack_app_classifier": "work_focus_write",
            WORK_FOCUS_FLOW_PROPERTY: flow,
            "team_id": str(team_id),
        },
    ).with_options(timeout=WRITE_TIMEOUT_SECONDS, max_retries=0)
    numbered = "\n".join(
        f"[{index}]{f' in #{message.channel_name}' if message.channel_name else ''}: {message.thread or message.content}"
        for index, message in enumerate(candidates, start=1)
    )
    numbered_threads = "\n\n".join(
        f"[{index}] in <#{thread.channel_id}>{' (you are in this thread)' if thread.involves_person else ''}:\n{thread.text}"
        for index, thread in enumerate(threads, start=1)
    )
    content = f"<person>{person.line}</person>\n<messages>\n{numbered}\n</messages>"
    if threads:
        content += f"\n<threads>\n{numbered_threads}\n</threads>"
    response = client.chat.completions.create(
        model=WRITE_MODEL,
        messages=[
            {"role": "system", "content": WRITE_INSTRUCTIONS},
            {"role": "user", "content": content},
        ],
        max_completion_tokens=WRITE_MAX_COMPLETION_TOKENS,
        response_format=_RESPONSE_FORMAT,
        # The gateway keeps no prompt or answer for analytics, because Slack forbids storing the messages.
        extra_headers={"X-PostHog-Privacy-Mode": "true"},
    )
    parsed = extract_json_object(response.choices[0].message.content or "") or {}
    return WorkFocus(
        intro=clip(str(parsed.get("intro") or ""), MAX_INTRO_CHARS),
        suggestions=_clean_suggestions(parsed.get("suggestions"), candidates),
        summary=_clean_summary(parsed.get("summary"), threads),
    )


CLIPPED = "…"


def clip(text: str, limit: int) -> str:
    """Cut model text that runs over its limit at a word boundary, so no word and no `<@U…>` mention is cut in half."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[: limit - len(CLIPPED)]
    if not text[len(head)].isspace():
        head = head.rsplit(None, 1)[0]
    return head.rstrip(" ,;:") + CLIPPED


def _clean_summary(raw: Any, threads: list[SummaryThread]) -> list[WorkFocusSummaryItem]:
    items = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = clip(str(item.get("text") or ""), MAX_SUMMARY_CHARS)
        source = item.get("source")
        thread = threads[source - 1] if isinstance(source, int) and 1 <= source <= len(threads) else None
        if text and thread is not None:
            items.append(WorkFocusSummaryItem(text=text, channel_id=thread.channel_id, permalink=thread.permalink))
    return items[:MAX_SUMMARY_ITEMS]


def _clean_suggestions(raw: Any, candidates: list[FoundMessage]) -> list[WorkFocusSuggestion]:
    suggestions = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        offer = clip(str(item.get("offer") or ""), MAX_OFFER_CHARS)
        request = clip(str(item.get("request") or ""), MAX_REQUEST_CHARS)
        source = item.get("source")
        if not offer or not request:
            continue
        found = candidates[source - 1] if isinstance(source, int) and 1 <= source <= len(candidates) else None
        suggestions.append(
            WorkFocusSuggestion(
                offer=offer,
                request=request,
                source_permalink=found.permalink if found else None,
                source_author_id=found.author_id if found else None,
                source_channel_name=found.channel_name if found else None,
            )
        )
    return suggestions[:MAX_SUGGESTIONS]


def source_line(suggestion: WorkFocusSuggestion, slack_user_id: str) -> str | None:
    """A link to the message a suggestion came from. The author shows as a mention, so Slack renders the name and
    PostHog keeps none."""
    if not suggestion.source_permalink:
        return None
    where = f" in #{suggestion.source_channel_name}" if suggestion.source_channel_name else ""
    if suggestion.source_author_id == slack_user_id:
        return f"<{suggestion.source_permalink}|Your message>{where}"
    with_author = f" with <@{suggestion.source_author_id}>" if suggestion.source_author_id else ""
    return f"<{suggestion.source_permalink}|Here's the thread>{with_author}{where}"


_USER_MENTION = re.compile(r"(<@[UW][A-Z0-9_]+>)")


def _safe_mrkdwn(text: str) -> str:
    """The models read whole Slack threads, so anyone in those channels can shape what they write. Only user mentions
    stay live; every other `<…>` is escaped, so a DM from the app cannot carry a disguised link or a broadcast."""
    return "".join(
        part if _USER_MENTION.fullmatch(part) else escape_slack_mrkdwn(part) for part in _USER_MENTION.split(text)
    )


def work_focus_blocks(
    integration: WorkspaceIntegration, focus: WorkFocus, slack_user_id: str, *, privacy: str = ONBOARDING_PRIVACY_LINE
) -> list[dict]:
    if not focus.summary:
        blocks: list[dict] = [section_block(f"{_safe_mrkdwn(focus.intro)} Here's where I can jump in:")]
    else:
        # Slackbot's own search answers: one line per finding, the channel after it, a small numbered link to the thread.
        lines = [
            f"• {_safe_mrkdwn(item.text.rstrip('.'))} in <#{item.channel_id}>."
            + (f" <{item.permalink}|[{number}]>" if item.permalink else "")
            for number, item in enumerate(focus.summary, start=1)
        ]
        blocks = [section_block(_safe_mrkdwn(focus.intro) + "\n" + "\n".join(lines))]
        if focus.suggestions:
            blocks.append(section_block("Here's where I can jump in:"))
    for index, suggestion in enumerate(focus.suggestions):
        # The DM posts with unfurling off, so the link shows no preview. The source line waits for the review thread.
        line = source_line(suggestion, slack_user_id)
        value: dict[str, Any] = {"integration_id": integration.id, "request": suggestion.request}
        if line:
            value["source"] = suggestion.source_permalink
            value["source_line"] = line
        number = len(focus.summary) + index + 1
        link = f" <{suggestion.source_permalink}|[{number}]>" if suggestion.source_permalink else ""
        blocks.append(
            {
                **section_block(f"• {_safe_mrkdwn(suggestion.offer)}{link}"),
                "block_id": f"{WORK_FOCUS_SUGGESTION_BLOCK_PREFIX}{index}",
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Do it"},
                    "action_id": WORK_FOCUS_TASK_ACTION_ID,
                    # The full request opens in a thread for the person to read before anything runs. Unicode stays as
                    # is, because escaping it can push the value past Slack's 2,000 characters.
                    "value": json.dumps(value, separators=(",", ":"), ensure_ascii=False),
                },
            }
        )
    blocks.append(context_block(privacy))
    return blocks


@frozen
class WorkFocusChoice:
    integration_id: int
    request: str
    source: str | None
    source_line: str | None


def read_work_focus_choice(action: dict[str, Any] | None) -> WorkFocusChoice | None:
    value = read_action_value(action) if action else None
    if not value:
        return None
    integration_id = value.get("integration_id")
    request = str(value.get("request") or "").strip()
    source = value.get("source")
    source = source if isinstance(source, str) and source.startswith("https://") else None
    line = value.get("source_line")
    line = line if source and isinstance(line, str) and len(line) <= 500 else None
    if not isinstance(integration_id, int) or not request:
        return None
    return WorkFocusChoice(integration_id=integration_id, request=request, source=source, source_line=line)


def work_focus_opened_blocks(blocks: list[dict], opened_block_ids: set[str]) -> list[dict]:
    """The DM's blocks with each opened suggestion's button replaced by a note, so the DM never brings one back."""
    marked = []
    for block in blocks:
        if block.get("block_id") in opened_block_ids and block.get("type") == "section" and "accessory" in block:
            text = (block.get("text") or {}).get("text") or ""
            block = {key: value for key, value in block.items() if key != "accessory"}
            block["text"] = {"type": "mrkdwn", "text": f"{text}\nOpened below"}
        marked.append(block)
    return marked


def work_focus_review_blocks(choice: WorkFocusChoice) -> list[dict]:
    """The full request, shown before it runs. The model writes it from other people's messages too, so the
    person reads what runs under their name before they start it."""
    value = {"integration_id": choice.integration_id, "request": choice.request}
    if choice.source and choice.source_line:
        value |= {"source": choice.source, "source_line": choice.source_line}
    blocks: list[dict] = [section_block(f"*Here's what I'd ask*\n{choice.request}")]
    if choice.source_line:
        blocks.append(context_block(choice.source_line))
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Start"},
                    "style": "primary",
                    "action_id": WORK_FOCUS_START_ACTION_ID,
                    "value": json.dumps(value, separators=(",", ":"), ensure_ascii=False),
                }
            ],
        }
    )
    return blocks


def work_focus_started_blocks(blocks: list[dict]) -> list[dict]:
    return [block for block in blocks if block.get("type") != "actions"] + [context_block("✅ Started")]


def start_work_focus(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    """Starts the work focus when the daily work focus flag is on for the person, their link can search and their
    organization allows AI data processing. Never raises, so a failed start never fails the account link or a click."""
    try:
        state = resolve_onboarding(integration.integration_id, slack_user_id)
        if state is not None and state.work_focus_at:
            return
        # The first work focus is the daily one's first run, so it rolls out with the same flag.
        if not _daily_work_focus_on(integration, slack_user_id):
            return
        if _search_token(integration, slack_user_id) is None or not has_ai_approval(integration.team_id):
            return
        # A task started from the DM reads its thread with the bot, so suggestions need the bot's DM scope.
        if SlackIntegration(integration).missing_scopes(frozenset({"im:history"})):
            return
        _start_workflow(integration, slack_user_id)
    except Exception:
        logger.warning("slack_app_work_focus_start_failed", slack_user_id=slack_user_id, exc_info=True)


def _start_workflow(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    # Deferred so temporalio stays off the import path of the link view.
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy  # noqa: PLC0415

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.slack_app.backend.temporal.slack_app_work_focus import (  # noqa: PLC0415
        SlackAppWorkFocusWorkflow,
        slack_app_work_focus_workflow_id,
    )
    from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs  # noqa: PLC0415

    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            SlackAppWorkFocusWorkflow.run,
            SlackAppWorkFocusInputs(
                integration_id=integration.id,
                slack_team_id=integration.integration_id,
                slack_user_id=slack_user_id,
            ),
            id=slack_app_work_focus_workflow_id(integration.integration_id, slack_user_id),
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            # The stored outcome is what keeps the work focus to one run, so a cleared outcome can run again.
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )
