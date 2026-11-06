"""Suggests first tasks from the person's recent Slack messages, once, after they link their account.

Slack's search terms forbid storing or copying what `assistant.search.context` returns. So the messages stay in
this process: one call searches, has Jev pick the messages that hold work, and has a model write the suggestions.
Only the suggestions and their links leave it.
"""

import json
import asyncio
from datetime import timedelta
from typing import Any

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
from posthog.token_bucket import BucketDecision, Budget, consume

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.actions import WORK_FOCUS_TASK_ACTION_ID
from products.slack_app.backend.logic.onboarding.checks import has_ai_approval
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.slack_user_oauth import linked_user_token
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# pinned: analytics event names, renaming breaks dashboards
SUGGESTIONS_SENT_EVENT = "slack app work focus suggestions sent"
SUGGESTION_CLICKED_EVENT = "slack app work focus suggestion clicked"

SEARCH_LOOKBACK = timedelta(days=30)
# Slack returns at most 20 results a page and allows a person about 10 search calls a minute. Three pages for each
# of the two searches stay at six calls, the most one person's run may take.
SEARCH_LIMIT = 20
SEARCH_PAGES = 3
# A workspace gets about 10 search calls a minute, so a burst of links waits for tokens.
SEARCH_BUDGET = Budget(burst=10, per_hour=600)
MIN_MESSAGES = 5
MAX_MESSAGE_CHARS = 500

# Onboarding promotes PostHog, so its model calls must not spend the team's AI credits.
WORK_FOCUS_AI_PRODUCT = "slack_app_onboarding"
# Jev ranks the messages, because a judgment costs far less than generated text, and only the few messages it keeps
# reach the model that writes. One question for each message, and a request takes 32 questions at most.
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

Keep it short and friendly. Never quote a message, never name a person, and never copy private details. Suggest \
nothing when no message shows work that PostHog can help with."""

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
                        },
                        "required": ["offer", "request"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["intro", "suggestions"],
            "additionalProperties": False,
        },
    },
}


class WorkFocusRateLimited(Exception):
    """Raised before anything is sent, so the activity can retry later."""


@frozen
class _FoundMessage:
    content: str
    channel_name: str | None


@frozen
class WorkFocusSuggestion:
    offer: str
    request: str


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
    # Not stored, so the work focus can still run once the organization allows AI data processing.
    if not has_ai_approval(integration.team_id):
        return "no_ai_consent"
    outcome = _find_and_send(integration, slack_user_id)
    update_onboarding(slack_workspace_id, slack_user_id, work_focus_outcome=outcome)
    return outcome


def _find_and_send(integration: WorkspaceIntegration, slack_user_id: str) -> str:
    token = linked_user_token(slack_user_id=slack_user_id, slack_team_id=integration.integration_id)
    if token is None or "search:read.public" not in token.scopes:
        return "no_search_scope"
    channel_types = [kind for kind, scope in _CHANNEL_TYPE_SCOPES.items() if scope in token.scopes]
    messages = _search_messages(integration, token.access_token, slack_user_id, channel_types)
    if messages is None:
        return "search_failed"
    if len(messages) < MIN_MESSAGES:
        return "not_enough_messages"
    try:
        candidates = _rank(integration, messages)
    except Exception:
        logger.warning("slack_app_work_focus_rank_failed", exc_info=True)
        return "rank_failed"
    if not candidates:
        return "nothing_actionable"
    try:
        focus = _write(integration, candidates)
    except Exception:
        logger.warning("slack_app_work_focus_model_failed", exc_info=True)
        return "model_failed"
    if not focus.suggestions:
        return "no_suggestions"
    SlackIntegration(integration).client.chat_postMessage(
        channel=slack_user_id,
        text=focus.intro,
        blocks=work_focus_blocks(integration, focus),
        unfurl_links=False,
        unfurl_media=False,
    )
    capture_slack_event(
        integration,
        SUGGESTIONS_SENT_EVENT,
        slack_user_id=slack_user_id,
        suggestion_count=len(focus.suggestions),
        message_count=len(messages),
        candidate_count=len(candidates),
    )
    return "sent"


def _search_messages(
    integration: WorkspaceIntegration, access_token: str, slack_user_id: str, channel_types: list[str]
) -> list[_FoundMessage] | None:
    client = SlackWebClient(
        access_token, source="slack_app_work_focus", workspace_id=integration.integration_id, app_id="posthog"
    )
    after = int((timezone.now() - SEARCH_LOOKBACK).timestamp())
    found: dict[tuple[str, str], _FoundMessage] = {}
    # The person's own messages, then the messages that mention them.
    for query in (f"from:<@{slack_user_id}>", f"<@{slack_user_id}>"):
        cursor = ""
        for _ in range(SEARCH_PAGES):
            decision = consume(f"slack_app:work_focus_search:{integration.integration_id}", SEARCH_BUDGET)
            if isinstance(decision, BucketDecision) and not decision.allowed:
                raise WorkFocusRateLimited
            params: dict[str, Any] = {
                "query": query,
                "channel_types": ",".join(channel_types),
                "content_types": "messages",
                "sort": "timestamp",
                "after": after,
                "limit": SEARCH_LIMIT,
                "include_bots": False,
            }
            if cursor:
                params["cursor"] = cursor
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
                content = str(message.get("content") or "").strip()
                key = (str(message.get("channel_id") or ""), str(message.get("message_ts") or ""))
                if content and not message.get("is_author_bot") and key not in found:
                    channel_name = message.get("channel_name")
                    found[key] = _FoundMessage(
                        content=content[:MAX_MESSAGE_CHARS],
                        channel_name=channel_name if isinstance(channel_name, str) and channel_name else None,
                    )
            cursor = str((response.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                break
    return list(found.values())


def _rank(integration: WorkspaceIntegration, messages: list[_FoundMessage]) -> list[_FoundMessage]:
    """The messages most likely to hold work for PostHog, most likely first."""
    # No TypeSafe fallback: the messages are customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=RANK_MODEL,
        ai_product=WORK_FOCUS_AI_PRODUCT,
        team_id=integration.team_id,
        properties={"slack_app_classifier": "work_focus_rank"},
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


def _write(integration: WorkspaceIntegration, candidates: list[_FoundMessage]) -> WorkFocus:
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=WORK_FOCUS_AI_PRODUCT,
        properties={"slack_app_classifier": "work_focus_write", "team_id": str(integration.team_id)},
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
        suggestions=_clean_suggestions(parsed.get("suggestions")),
    )


def _clean_suggestions(raw: Any) -> list[WorkFocusSuggestion]:
    suggestions = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        offer = str(item.get("offer") or "").strip()[:MAX_OFFER_CHARS]
        request = str(item.get("request") or "").strip()[:MAX_REQUEST_CHARS]
        if offer and request:
            suggestions.append(WorkFocusSuggestion(offer=offer, request=request))
    return suggestions[:MAX_SUGGESTIONS]


def work_focus_blocks(integration: WorkspaceIntegration, focus: WorkFocus) -> list[dict]:
    blocks: list[dict] = [section_block(f"{focus.intro} Here's where I can jump in:")]
    for suggestion in focus.suggestions:
        blocks.append(
            {
                **section_block(f"• {suggestion.offer}"),
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Do it 🚀", "emoji": True},
                    "action_id": WORK_FOCUS_TASK_ACTION_ID,
                    # The full request opens the task's thread, so the person sees what runs.
                    "value": json.dumps(
                        {"integration_id": integration.id, "request": suggestion.request}, separators=(",", ":")
                    ),
                },
            }
        )
    blocks.append(
        context_block("🔒 I read your recent messages once and kept nothing. Each one starts its own thread.")
    )
    return blocks


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
