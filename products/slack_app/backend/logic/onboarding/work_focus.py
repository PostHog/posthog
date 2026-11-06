"""Suggests first tasks from the person's recent Slack messages, once, after they link their account.

Slack's search terms forbid storing or copying what `assistant.search.context` returns. So the messages stay in
this process: one call searches and asks the model, and only the suggestions and their links leave it.
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
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models.integration import SlackIntegration
from posthog.token_bucket import BucketDecision, Budget, consume

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.actions import WORK_FOCUS_TASK_ACTION_ID
from products.slack_app.backend.services.slack_messages import context_block, section_block
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.slack_user_oauth import linked_user_token
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# pinned: analytics event names, renaming breaks dashboards
SUGGESTIONS_SENT_EVENT = "slack app work focus suggestions sent"
SUGGESTION_CLICKED_EVENT = "slack app work focus suggestion clicked"

SEARCH_LOOKBACK = timedelta(days=30)
# Slack returns at most 20 results for each call, and allows a person about 10 search calls a minute.
SEARCH_LIMIT = 20
# A workspace gets about 10 search calls a minute, so a burst of links waits for tokens.
SEARCH_BUDGET = Budget(burst=10, per_hour=600)
MIN_MESSAGES = 5
MAX_MESSAGE_CHARS = 500
MAX_SUGGESTIONS = 3
MAX_LABEL_CHARS = 60
MAX_PROMPT_CHARS = 500
WORK_FOCUS_MODEL = "gpt-6-luna"
WORK_FOCUS_TIMEOUT_SECONDS = 30.0
WORK_FOCUS_MAX_COMPLETION_TOKENS = 2048

_CHANNEL_TYPE_SCOPES = {
    "public_channel": "search:read.public",
    "private_channel": "search:read.private",
    "im": "search:read.im",
    "mpim": "search:read.mpim",
}

WORK_FOCUS_INSTRUCTIONS = """You read a person's recent Slack messages and suggest first tasks for PostHog, an AI agent \
that answers questions from product data (analytics, session replay, errors, feature flags, experiments) and opens \
pull requests in connected repositories.

Suggest at most 3 tasks that would help this person with the work their messages show. Each task needs:
- "label": a short button text in sentence case, at most 60 characters.
- "prompt": the task as the person would ask it, at most 500 characters.
- "source": the number of the message the task comes from, or 0.

Never quote a message, never name a person, and never copy private details into a label or a prompt. \
Write the task in your own words. Suggest nothing when the messages show no work that PostHog can help with."""

_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "slack_app_work_focus",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "prompt": {"type": "string"},
                            "source": {"type": "integer"},
                        },
                        "required": ["label", "prompt", "source"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["suggestions"],
            "additionalProperties": False,
        },
    },
}


class WorkFocusRateLimited(Exception):
    """Raised before anything is sent, so the activity can retry later."""


@frozen
class _FoundMessage:
    content: str
    permalink: str | None


@frozen
class WorkFocusSuggestion:
    label: str
    prompt: str
    source_permalink: str | None


def find_and_send_work_focus(integration: WorkspaceIntegration, slack_user_id: str) -> str:
    """Returns the outcome, which is also stored, so the work focus never runs twice for a person."""
    slack_workspace_id = integration.integration_id
    state = resolve_onboarding(slack_workspace_id, slack_user_id)
    if state is not None and state.work_focus_at:
        return "already_done"
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
        suggestions = _suggest(integration, messages)
    except Exception:
        logger.warning("slack_app_work_focus_model_failed", exc_info=True)
        return "model_failed"
    if not suggestions:
        return "no_suggestions"
    SlackIntegration(integration).client.chat_postMessage(
        channel=slack_user_id,
        text="Here's what I can help you with",
        blocks=work_focus_blocks(integration, suggestions),
    )
    capture_slack_event(
        integration,
        SUGGESTIONS_SENT_EVENT,
        slack_user_id=slack_user_id,
        suggestion_count=len(suggestions),
        message_count=len(messages),
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
        decision = consume(f"slack_app:work_focus_search:{integration.integration_id}", SEARCH_BUDGET)
        if isinstance(decision, BucketDecision) and not decision.allowed:
            raise WorkFocusRateLimited
        try:
            response = client.api_call(
                "assistant.search.context",
                params={
                    "query": query,
                    "channel_types": ",".join(channel_types),
                    "content_types": "messages",
                    "sort": "timestamp",
                    "after": after,
                    "limit": SEARCH_LIMIT,
                    "include_bots": False,
                },
            )
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
                permalink = message.get("permalink")
                found[key] = _FoundMessage(
                    content=content[:MAX_MESSAGE_CHARS], permalink=permalink if isinstance(permalink, str) else None
                )
    return list(found.values())


def _suggest(integration: WorkspaceIntegration, messages: list[_FoundMessage]) -> list[WorkFocusSuggestion]:
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product="slack_app",
        properties={"slack_app_classifier": "work_focus", "team_id": str(integration.team_id)},
    ).with_options(timeout=WORK_FOCUS_TIMEOUT_SECONDS, max_retries=0)
    numbered = "\n".join(f"[{index}] {message.content}" for index, message in enumerate(messages, start=1))
    response = client.chat.completions.create(
        model=WORK_FOCUS_MODEL,
        messages=[
            {"role": "system", "content": WORK_FOCUS_INSTRUCTIONS},
            {"role": "user", "content": f"<messages>\n{numbered}\n</messages>"},
        ],
        max_completion_tokens=WORK_FOCUS_MAX_COMPLETION_TOKENS,
        response_format=_RESPONSE_FORMAT,
        # The gateway keeps no prompt or answer for analytics, because Slack forbids storing the messages.
        extra_headers={"X-PostHog-Privacy-Mode": "true"},
    )
    parsed = extract_json_object(response.choices[0].message.content or "") or {}
    return _clean_suggestions(parsed.get("suggestions"), messages)


def _clean_suggestions(raw: Any, messages: list[_FoundMessage]) -> list[WorkFocusSuggestion]:
    suggestions = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:MAX_LABEL_CHARS]
        prompt = str(item.get("prompt") or "").strip()[:MAX_PROMPT_CHARS]
        source = item.get("source")
        if not label or not prompt:
            continue
        permalink = messages[source - 1].permalink if isinstance(source, int) and 1 <= source <= len(messages) else None
        suggestions.append(WorkFocusSuggestion(label=label, prompt=prompt, source_permalink=permalink))
    return suggestions[:MAX_SUGGESTIONS]


def work_focus_blocks(integration: WorkspaceIntegration, suggestions: list[WorkFocusSuggestion]) -> list[dict]:
    blocks: list[dict] = [
        section_block(
            "*Here's what I can help you with*\n"
            "I read your recent Slack messages once to suggest these. I didn't keep the messages."
        )
    ]
    for suggestion in suggestions:
        source = f" <{suggestion.source_permalink}|Based on this message>" if suggestion.source_permalink else ""
        blocks.append(
            {
                **section_block(f"{suggestion.label}.{source}"),
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Start"},
                    "action_id": WORK_FOCUS_TASK_ACTION_ID,
                    "value": json.dumps(
                        {"integration_id": integration.id, "label": suggestion.label, "prompt": suggestion.prompt},
                        separators=(",", ":"),
                    ),
                },
            }
        )
    blocks.append(context_block("Each one starts a task in its own thread."))
    return blocks


def start_work_focus(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    """Never raises, so a failed start never fails the account link."""
    try:
        state = resolve_onboarding(integration.integration_id, slack_user_id)
        if state is not None and state.work_focus_at:
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
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
    )
