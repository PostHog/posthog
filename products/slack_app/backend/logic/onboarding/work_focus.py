"""Suggests first tasks from the person's recent Slack messages, once, after they link their account.

Slack's search terms forbid storing or copying what `assistant.search.context` returns. So the messages stay in
this process: one call searches, has Jev pick the messages that hold work, and has a model write the suggestions.
Only the suggestions and their links leave it.
"""

import json
import asyncio
from datetime import datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
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
from posthog.token_bucket import BucketDecision, Budget, consume, refund

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_daily_work_focus_enabled
from products.slack_app.backend.logic.daily_focus import (
    daily_focus_footer_block,
    person_zone,
    reschedule_daily_focus,
    resolve_daily_focus,
    turn_on_daily_focus,
)
from products.slack_app.backend.logic.onboarding.actions import WORK_FOCUS_START_ACTION_ID, WORK_FOCUS_TASK_ACTION_ID
from products.slack_app.backend.logic.onboarding.checks import has_ai_approval
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, read_action_value
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.slack_user_oauth import linked_user_token
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# pinned: analytics event names, renaming breaks dashboards
SUGGESTIONS_SENT_EVENT = "slack app work focus suggestions sent"
SUGGESTION_CLICKED_EVENT = "slack app work focus suggestion clicked"
SUGGESTION_STARTED_EVENT = "slack app work focus suggestion started"
WORK_FOCUS_SUGGESTION_BLOCK_PREFIX = "work_focus_suggestion_"

SEARCH_LOOKBACK = timedelta(days=30)
# Slack returns at most 20 results a page and allows a person about 10 search calls a minute. Three pages for each
# of the two searches stay at six calls, the most one person's run may take.
SEARCH_LIMIT = 20
SEARCH_PAGES = 3
# A workspace gets about 10 search calls a minute, so a burst of links waits for tokens.
SEARCH_BUDGET = Budget(burst=10, per_hour=600)
# A daily run reads one workday, so one page of each search is enough.
DAILY_SEARCH_PAGES = 1
DAILY_SEARCH_CALLS = 2 * DAILY_SEARCH_PAGES
# Daily runs in one workspace start this far apart, so together they stay within its search budget.
DAILY_RUN_SPACING_SECONDS = 3600 * DAILY_SEARCH_CALLS // SEARCH_BUDGET.per_hour
MIN_MESSAGES = 5
# One workday can bring a single message worth acting on.
DAILY_MIN_MESSAGES = 1
SENT_KEY_TIMEOUT_SECONDS = 2 * 24 * 60 * 60
MAX_MESSAGE_CHARS = 500

# The model calls spend the team's PostHog AI credits, the same as the other Slack app calls.
WORK_FOCUS_AI_PRODUCT = "slack_app"
# Every Slack app call shares the product, so the captured generation carries this property to say which run made it.
WORK_FOCUS_FLOW_PROPERTY = "slack_app_flow"
WorkFocusFlow = Literal["slack_app_onboarding", "slack_app_daily_focus"]
# Jev ranks the messages, because a judgment costs far less than generated text, and only the few messages it keeps
# reach the model that writes. One question for each message, and a request takes 32 questions at most.
ONBOARDING_PRIVACY_LINE = "🔒 I read your recent messages once and kept nothing. Each one starts its own thread."

RANK_MODEL = DEFAULT_DECISION_MODEL
RANK_BATCH_SIZE = GATEWAY_MAX_QUESTIONS
RANK_MIN_PROBABILITY = 0.5
RANK_TIMEOUT_SECONDS = 15.0
MAX_CANDIDATES = 5
RANK_INSTRUCTIONS = (
    "`messages` holds Slack messages that a person wrote or that mention them. For the message this question names, "
    "decide whether it describes work that PostHog could do for this person now: answer a product data question, "
    "investigate a bug or an error, or change code in a connected repository."
)
RANK_TRUE = "The message asks for, reports or plans work of that kind."
RANK_FALSE = "The message is chat, a greeting, a status note or work that PostHog cannot help with."

WRITE_MODEL = "gpt-6-luna"
WRITE_TIMEOUT_SECONDS = 30.0
WRITE_MAX_COMPLETION_TOKENS = 2048
MAX_SUGGESTIONS = 3
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
opens pull requests in connected repositories. The numbered messages are recent Slack messages that the person wrote \
or that mention them.

Return:
- "intro": one short, warm sentence to the person, in the second person, that names what their recent work is \
about. Start it with one fitting emoji. At most 120 characters. For example: "👀 Looks like your week is all about \
Slack handoffs and feature tips."
- "suggestions": at most 3 tasks that PostHog could do for them, the most useful first. Each task has:
  - "offer": one short line in the second person that ends with a question. Start it with one emoji that fits the \
task. At most 100 characters. For example: "📈 Chart previews ignore edited query params. Want me to find out why?"
  - "request": the full task, written as the person would ask PostHog, such as "Find out why chart link previews \
ignore edited query parameters, and open a pull request with the fix." At most 500 characters.
  - "source": the number of the message the task comes from.

Keep it short and friendly, and never use em dashes. Never quote a message, never name a person, and never copy \
private details. Suggest nothing when no message shows work that PostHog can help with."""

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
            },
            "required": ["intro", "suggestions"],
            "additionalProperties": False,
        },
    },
}


class WorkFocusTransientError(Exception):
    """Raised before anything is sent, so the activity retries and no outcome is stored."""


class WorkFocusRateLimited(Exception):
    """Raised before anything is sent, so the activity can retry later."""


@frozen
class _FoundMessage:
    content: str
    channel_name: str | None
    permalink: str | None
    author_id: str | None


@frozen
class WorkFocusSuggestion:
    offer: str
    request: str
    source_permalink: str | None = None
    source_author_id: str | None = None
    source_channel_name: str | None = None


@frozen
class WorkFocus:
    intro: str
    suggestions: list[WorkFocusSuggestion]


def find_and_send_work_focus(integration: WorkspaceIntegration, slack_user_id: str) -> str:
    """Returns the outcome, which is also stored, so the work focus never runs twice for a person."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is not None and state.work_focus_at:
        return "already_done"
    # Not stored, so the work focus can still run once the person can reach the project, and the organization allows
    # AI data processing and has credits.
    if not _has_project_access(integration, slack_user_id):
        return "no_project_access"
    if not has_ai_approval(integration.team_id):
        return "no_ai_consent"
    if _out_of_ai_credits(integration):
        return "out_of_ai_credits"
    outcome = _find_and_send(integration, slack_user_id)
    update_onboarding(slack_workspace_id, slack_user_id, work_focus_outcome=outcome)
    return outcome


def find_and_send_daily_focus(integration: WorkspaceIntegration, slack_user_id: str, *, since: datetime) -> str:
    """One workday's work focus, from the messages sent after ``since``. A quiet day sends nothing."""
    sent_key = f"slack_app_daily_focus_sent:{integration.integration_id}:{slack_user_id}:{int(since.timestamp())}"
    if cache.get(sent_key):
        return "already_sent"
    if not is_slack_app_daily_work_focus_enabled(integration):
        return "flag_off"
    daily = resolve_daily_focus(integration.integration_id, slack_user_id)
    if not daily.enabled:
        return "turned_off"
    if not _has_project_access(integration, slack_user_id):
        return "no_project_access"
    if not has_ai_approval(integration.team_id):
        return "no_ai_consent"
    if _out_of_ai_credits(integration):
        return "out_of_ai_credits"
    # A task started from the DM reads its thread with the bot, so suggestions need the bot's DM scope.
    if SlackIntegration(integration).missing_scopes(frozenset({"im:history"})):
        return "missing_bot_scope"
    zone = person_zone(integration, slack_user_id)
    reschedule_daily_focus(integration, slack_user_id, zone)
    found = _find(
        integration,
        slack_user_id,
        after=since,
        min_messages=DAILY_MIN_MESSAGES,
        pages=DAILY_SEARCH_PAGES,
        flow="slack_app_daily_focus",
    )
    if isinstance(found, str):
        return found
    blocks = [
        *work_focus_blocks(integration, found.focus, slack_user_id, privacy=_daily_privacy_line(since, zone)),
        daily_focus_footer_block(integration, daily.at, zone, first=False),
    ]
    # Set before the DM goes out. When Slack takes the DM but the response times out, the retry sends nothing.
    if not cache.add(sent_key, True, timeout=SENT_KEY_TIMEOUT_SECONDS):
        return "already_sent"
    return _post(integration, slack_user_id, found, blocks, mode="daily")


def _has_project_access(integration: WorkspaceIntegration, slack_user_id: str) -> bool:
    """The run spends the project's AI credits. An organization member can link their Slack account without access to
    this project, and a Slack link outlives an organization membership."""
    return OnboardingContext(integration=integration, slack_user_id=slack_user_id).has_project_access


def _out_of_ai_credits(integration: WorkspaceIntegration) -> bool:
    """Nobody asked for a work focus, so a team without AI credits gets no run and no message about it."""
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the Slack import path
        is_team_over_ai_credit_budget,
    )

    try:
        return is_team_over_ai_credit_budget(integration.team.api_token)
    except Exception:
        # The quota cache reads Redis. An outage must not stop the runs of teams that have credits.
        logger.warning("slack_app_daily_focus_ai_credit_check_failed", team_id=integration.team_id, exc_info=True)
        return False


def _ready_to_send(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    # Stored before the DM goes out. When Slack takes the DM but the response times out, the retry sees this and
    # sends nothing, because a second DM would carry a second set of buttons.
    update_onboarding(integration.integration_id, slack_user_id, work_focus_outcome="sending")


@frozen
class _DailyFooter:
    at: time
    zone: ZoneInfo


def _daily_focus_footer(integration: WorkspaceIntegration, slack_user_id: str) -> _DailyFooter | None:
    """The onboarding turns the daily work focus on, unless the person already chose. The footer shows while it is
    on."""
    if not is_slack_app_daily_work_focus_enabled(integration):
        return None
    daily = resolve_daily_focus(integration.integration_id, slack_user_id)
    if daily.enabled is None:
        turn_on_daily_focus(integration, slack_user_id, source="onboarding")
    elif not daily.enabled:
        return None
    return _DailyFooter(at=daily.at, zone=person_zone(integration, slack_user_id))


def _find_and_send(integration: WorkspaceIntegration, slack_user_id: str) -> str:
    found = _find(
        integration,
        slack_user_id,
        after=timezone.now() - SEARCH_LOOKBACK,
        min_messages=MIN_MESSAGES,
        flow="slack_app_onboarding",
    )
    if found == "no_search_scope":
        return found
    # Turned on before the quiet outcomes return and before the DM, so a retry after a failed write still finds it on.
    daily = _daily_focus_footer(integration, slack_user_id)
    if isinstance(found, str):
        return found
    blocks = work_focus_blocks(integration, found.focus, slack_user_id)
    if daily is not None:
        blocks.append(daily_focus_footer_block(integration, daily.at, daily.zone, first=True))
    _ready_to_send(integration, slack_user_id)
    return _post(integration, slack_user_id, found, blocks, mode="onboarding")


@frozen
class _Found:
    focus: WorkFocus
    message_count: int
    candidate_count: int


def _find(
    integration: WorkspaceIntegration,
    slack_user_id: str,
    *,
    after: datetime,
    min_messages: int,
    flow: WorkFocusFlow,
    pages: int = SEARCH_PAGES,
) -> _Found | str:
    """The suggestions from the messages sent after ``after``, or the outcome that stops the run."""
    token = linked_user_token(slack_user_id=slack_user_id, slack_team_id=integration.integration_id)
    if token is None or "search:read.public" not in token.scopes:
        return "no_search_scope"
    channel_types = [kind for kind, scope in _CHANNEL_TYPE_SCOPES.items() if scope in token.scopes]
    messages = _search_messages(integration, token.access_token, slack_user_id, channel_types, after=after, pages=pages)
    if messages is None:
        raise WorkFocusTransientError("search failed")
    if len(messages) < min_messages:
        return "not_enough_messages"
    try:
        candidates = _rank(integration, messages, flow=flow)
    except Exception as error:
        logger.warning("slack_app_work_focus_rank_failed", exc_info=True)
        raise WorkFocusTransientError("rank failed") from error
    if not candidates:
        return "nothing_actionable"
    try:
        focus = _write(integration, candidates, flow=flow)
    except Exception as error:
        logger.warning("slack_app_work_focus_model_failed", exc_info=True)
        raise WorkFocusTransientError("write failed") from error
    if not focus.suggestions:
        return "no_suggestions"
    return _Found(focus=focus, message_count=len(messages), candidate_count=len(candidates))


def _post(
    integration: WorkspaceIntegration, slack_user_id: str, found: _Found, blocks: list[dict], *, mode: str
) -> str:
    try:
        SlackIntegration(integration).client.chat_postMessage(
            channel=slack_user_id,
            text=found.focus.intro,
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
        message_count=found.message_count,
        candidate_count=found.candidate_count,
        mode=mode,
    )
    return "sent"


def _daily_privacy_line(since: datetime, zone: ZoneInfo) -> str:
    since_day = since.astimezone(zone).date()
    today = timezone.now().astimezone(zone).date()
    when = "yesterday" if since_day == today - timedelta(days=1) else since_day.strftime("%A")
    return f"🔒 I read your messages since {when} and kept nothing. Each one starts its own thread."


def _search_messages(
    integration: WorkspaceIntegration,
    access_token: str,
    slack_user_id: str,
    channel_types: list[str],
    *,
    after: datetime,
    pages: int = SEARCH_PAGES,
) -> list[_FoundMessage] | None:
    client = SlackWebClient(
        access_token, source="slack_app_work_focus", workspace_id=integration.integration_id, app_id="posthog"
    )
    found: dict[tuple[str, str], _FoundMessage] = {}
    # All calls are reserved at once, so two runs cannot each take one call and both fail on the next one.
    bucket = f"slack_app:work_focus_search:{integration.integration_id}"
    cost = 2 * pages
    decision = consume(bucket, SEARCH_BUDGET, cost=cost)
    if isinstance(decision, BucketDecision) and not decision.allowed:
        raise WorkFocusRateLimited
    calls = 0
    try:
        # The person's own messages, then the messages that mention them.
        for query in (f"from:<@{slack_user_id}>", f"<@{slack_user_id}>"):
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


def _collect(found: dict[tuple[str, str], _FoundMessage], message: dict[str, Any]) -> None:
    content = str(message.get("content") or "").strip()
    key = (str(message.get("channel_id") or ""), str(message.get("message_ts") or ""))
    if not content or message.get("is_author_bot") or key in found:
        return
    channel_name = message.get("channel_name")
    permalink = message.get("permalink")
    author_id = message.get("author_user_id")
    found[key] = _FoundMessage(
        content=content[:MAX_MESSAGE_CHARS],
        # A DM has no channel name worth showing, so only channels keep theirs.
        channel_name=channel_name
        if isinstance(channel_name, str) and channel_name and key[0][:1] in ("C", "G")
        else None,
        author_id=author_id if isinstance(author_id, str) and author_id else None,
        permalink=permalink if isinstance(permalink, str) and permalink.startswith("https://") else None,
    )


def _rank(
    integration: WorkspaceIntegration, messages: list[_FoundMessage], *, flow: WorkFocusFlow
) -> list[_FoundMessage]:
    """The messages most likely to hold work for PostHog, most likely first."""
    # No TypeSafe fallback: the messages are customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=RANK_MODEL,
        ai_product=WORK_FOCUS_AI_PRODUCT,
        team_id=integration.team_id,
        properties={"slack_app_classifier": "work_focus_rank", WORK_FOCUS_FLOW_PROPERTY: flow},
        timeout=RANK_TIMEOUT_SECONDS,
        privacy_mode=True,
    )
    scored: list[tuple[float, int]] = []
    for batch_start in range(0, len(messages), RANK_BATCH_SIZE):
        batch = messages[batch_start : batch_start + RANK_BATCH_SIZE]
        keys = [f"m{batch_start + offset}" for offset in range(len(batch))]
        result = client.decide(
            state={"messages": {key: message.content for key, message in zip(keys, batch)}},
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


def _write(integration: WorkspaceIntegration, candidates: list[_FoundMessage], *, flow: WorkFocusFlow) -> WorkFocus:
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=WORK_FOCUS_AI_PRODUCT,
        properties={
            "slack_app_classifier": "work_focus_write",
            WORK_FOCUS_FLOW_PROPERTY: flow,
            "team_id": str(integration.team_id),
        },
    ).with_options(timeout=WRITE_TIMEOUT_SECONDS, max_retries=0)
    numbered = "\n".join(
        f"[{index}]{f' in #{message.channel_name}' if message.channel_name else ''}: {message.content}"
        for index, message in enumerate(candidates, start=1)
    )
    response = client.chat.completions.create(
        model=WRITE_MODEL,
        messages=[
            {"role": "system", "content": WRITE_INSTRUCTIONS},
            {"role": "user", "content": f"<messages>\n{numbered}\n</messages>"},
        ],
        max_completion_tokens=WRITE_MAX_COMPLETION_TOKENS,
        response_format=_RESPONSE_FORMAT,
        # The gateway keeps no prompt or answer for analytics, because Slack forbids storing the messages.
        extra_headers={"X-PostHog-Privacy-Mode": "true"},
    )
    parsed = extract_json_object(response.choices[0].message.content or "") or {}
    return WorkFocus(
        intro=str(parsed.get("intro") or "").strip()[:MAX_INTRO_CHARS],
        suggestions=_clean_suggestions(parsed.get("suggestions"), candidates),
    )


def _clean_suggestions(raw: Any, candidates: list[_FoundMessage]) -> list[WorkFocusSuggestion]:
    suggestions = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        offer = str(item.get("offer") or "").strip()[:MAX_OFFER_CHARS]
        request = str(item.get("request") or "").strip()[:MAX_REQUEST_CHARS]
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


def work_focus_blocks(
    integration: WorkspaceIntegration, focus: WorkFocus, slack_user_id: str, *, privacy: str = ONBOARDING_PRIVACY_LINE
) -> list[dict]:
    blocks: list[dict] = [section_block(f"{focus.intro} Here's where I can jump in:")]
    for index, suggestion in enumerate(focus.suggestions):
        # The DM posts with unfurling off, so the link shows no preview.
        line = source_line(suggestion, slack_user_id)
        value: dict[str, Any] = {"integration_id": integration.id, "request": suggestion.request}
        if line:
            value["source"] = suggestion.source_permalink
            value["source_line"] = line
        blocks.append(
            {
                **section_block(f"• {suggestion.offer}" + (f"\n      ◦ {line}" if line else "")),
                "block_id": f"{WORK_FOCUS_SUGGESTION_BLOCK_PREFIX}{index}",
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Do it 🚀", "emoji": True},
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
            block["text"] = {"type": "mrkdwn", "text": f"{text}\n👇 Opened below"}
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
                    "text": {"type": "plain_text", "text": "Start 🚀", "emoji": True},
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
    """Starts the work focus when the person's link can search and their organization allows AI data processing.
    Never raises, so a failed start never fails the account link or a click."""
    try:
        state = resolve_onboarding(integration.integration_id, slack_user_id)
        if state is not None and state.work_focus_at:
            return
        token = linked_user_token(slack_user_id=slack_user_id, slack_team_id=integration.integration_id)
        if token is None or "search:read.public" not in token.scopes or not has_ai_approval(integration.team_id):
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
