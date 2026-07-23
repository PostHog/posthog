"""Webhook endpoint for the central PostHog Telegram bot.

Telegram delivers every update for the bot to a single URL, so whichever Cloud region
receives an update routes it to the region that owns the chat's binding (mirroring the
Slack event flow): a locally bound chat is handled here, an unbound one triggers a
claims probe and, when the other region claims it (or the probe fails), the original
request is proxied across with the loop header set.

Kept deliberately small: parse, dedup, route commands, gate, dispatch to Temporal.
Telegram retries on non-200 with backoff, so transient failures self-heal.
"""

import json
import asyncio
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import requests
import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.integration import Integration
from posthog.temporal.ai.telegram_app import TelegramAppMentionWorkflow, TelegramAppMentionWorkflowInputs
from posthog.temporal.common.client import sync_connect

from products.slack_app.backend.api import (
    REGION_PROXY_HEADER,
    _proxy_event_to_region,
    cross_region_routing_enabled,
    other_region_domain,
    was_proxied,
)
from products.slack_app.backend.feature_flags import is_telegram_app_enabled
from products.slack_app.backend.providers import ChatProviderError, TelegramChatProvider
from products.slack_app.backend.services.region_auth import (
    REGION_SIGNATURE_HEADER,
    REGION_TIMESTAMP_HEADER,
    region_claims_secret,
    sign_region_request,
)
from products.slack_app.backend.services.telegram_api import TelegramApiError, TelegramBotClient, get_bot_identity
from products.slack_app.backend.services.telegram_link import (
    _command_argument,
    find_linked_telegram_user,
    handle_connect_redemption,
    handle_start_redemption,
)

logger = structlog.get_logger(__name__)

_UPDATE_DEDUP_TTL_SECONDS = 24 * 60 * 60
_CHAT_CLAIMS_CACHE_TTL_SECONDS = 60
_CHAT_CLAIMS_TIMEOUT_SECONDS = (1, 1)


def _reply(chat_id: str, message: dict[str, Any], text: str) -> None:
    """Best-effort reply; the webhook must ack regardless."""
    try:
        TelegramBotClient().send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=str(message.get("message_id") or "") or None,
        )
    except TelegramApiError as e:
        logger.warning("slack_app_telegram_webhook_reply_failed", chat_id=chat_id, error=str(e))


def _should_handle(message: dict[str, Any], chat_type: str) -> bool:
    """DMs: every message. Groups: only bot @mentions or replies to the bot."""
    if chat_type == "private":
        return True
    if chat_type not in ("group", "supergroup"):
        return False
    try:
        identity = get_bot_identity()
    except TelegramApiError:
        return False
    username = identity.get("username")
    if username and f"@{username}" in str(message.get("text") or ""):
        return True
    reply_to = message.get("reply_to_message")
    if isinstance(reply_to, dict):
        return (reply_to.get("from") or {}).get("id") == identity.get("id")
    return False


def _does_other_region_claim_chat(chat_id: str, *, incoming_host: str) -> bool | None:
    """Telegram flavor of the Slack workspace-claims probe; definitive answers cached."""
    cache_key = f"telegram_app:chat_claims:{chat_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, bool):
        return cached

    target_domain = other_region_domain(incoming_host)
    scheme = "http" if settings.DEBUG else "https"
    target_url = f"{scheme}://{target_domain}/chat/telegram/workspace/claims/"
    body = json.dumps({"workspace_id": chat_id, "kinds": ["telegram"]}).encode("utf-8")
    signature, ts = sign_region_request(body, region_claims_secret("telegram"))

    try:
        response = requests.post(
            target_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                REGION_SIGNATURE_HEADER: signature,
                REGION_TIMESTAMP_HEADER: ts,
                REGION_PROXY_HEADER: "1",
            },
            timeout=_CHAT_CLAIMS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("slack_app_telegram_chat_claims_failed", target_url=target_url, error=str(exc))
        return None
    if response.status_code != 200:
        logger.warning(
            "slack_app_telegram_chat_claims_non_200", target_url=target_url, status_code=response.status_code
        )
        return None
    try:
        claimed = response.json().get("claimed")
    except ValueError:
        return None
    if not isinstance(claimed, bool):
        return None
    cache.set(cache_key, claimed, timeout=_CHAT_CLAIMS_CACHE_TTL_SECONDS)
    return claimed


def _route_unbound(
    request: HttpRequest, message: dict[str, Any], chat_id: str, chat_type: str, update_id: int
) -> HttpResponse:
    """No local binding for this chat: proxy to the other region if it claims the
    chat (or we can't tell), otherwise answer with connect instructions."""
    if cross_region_routing_enabled() and not was_proxied(request):
        claimed = _does_other_region_claim_chat(chat_id, incoming_host=request.get_host())
        if claimed is not False:
            # Claimed there, or unknown: optimistic proxy, like the Slack flow.
            if _proxy_event_to_region(request, other_region_domain(request.get_host())) is not None:
                return HttpResponse(status=200)
            # Unmark the update so Telegram's retry isn't swallowed by the dedup guard.
            cache.delete(f"telegram_app:update:{update_id}")
            return HttpResponse(status=502)

    if chat_type == "private":
        _reply(
            chat_id,
            message,
            "This chat isn't connected to a PostHog project yet. "
            f"Open {settings.SITE_URL}/telegram/link/start/?team_id=<your project id> while logged in to PostHog.",
        )
    else:
        _reply(
            chat_id,
            message,
            "This group isn't connected to a PostHog project yet. An org member can connect it: "
            f"open {settings.SITE_URL}/telegram/connect/start/?team_id=<your project id> and paste the command here.",
        )
    return HttpResponse(status=200)


def _start_telegram_mention_workflow(
    integration: Integration, chat_id: str, message: dict[str, Any], user_id: int, update_id: int
) -> None:
    inputs = TelegramAppMentionWorkflowInputs(
        integration_id=integration.id,
        chat_id=chat_id,
        message=message,
        user_id=user_id,
        update_id=update_id,
    )
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            TelegramAppMentionWorkflow.run,
            inputs,
            # update_id is globally unique per bot, so redeliveries collapse onto the
            # same execution (second dedup layer after the cache guard).
            id=f"telegram-app-mention-{integration.id}:{update_id}",
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )


@csrf_exempt
def telegram_event_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        TelegramChatProvider.validate_webhook(request)
    except ChatProviderError as e:
        logger.warning("slack_app_telegram_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    update_id = data.get("update_id")
    message = data.get("message")
    if not isinstance(update_id, int) or not isinstance(message, dict):
        # edited_message / channel_post / reactions etc. — nothing to do.
        return HttpResponse(status=200)
    if not cache.add(f"telegram_app:update:{update_id}", "1", timeout=_UPDATE_DEDUP_TTL_SECONDS):
        return HttpResponse(status=200)

    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    chat_type = str(chat.get("type") or "")
    text = str(message.get("text") or "")
    if not chat_id:
        return HttpResponse(status=200)

    # Link/bind commands work even in unbound chats — they're how a chat GETS bound.
    if chat_type == "private" and _command_argument(text, "start") is not None:
        _reply(chat_id, message, handle_start_redemption(message))
        return HttpResponse(status=200)
    if chat_type in ("group", "supergroup") and _command_argument(text, "connect") is not None:
        _reply(chat_id, message, handle_connect_redemption(message))
        return HttpResponse(status=200)

    if not _should_handle(message, chat_type):
        return HttpResponse(status=200)

    integration = (
        Integration.objects.filter(kind="telegram", integration_id=chat_id)
        .select_related("team", "team__organization")
        .first()
    )
    if integration is None:
        return _route_unbound(request, message, chat_id, chat_type, update_id)

    if not is_telegram_app_enabled(integration):
        # Flagged-off chats stay completely dark — no reply, no workflow.
        return HttpResponse(status=200)

    sender_id = str((message.get("from") or {}).get("id") or "")
    user = find_linked_telegram_user(
        telegram_user_id=sender_id,
        candidate_org_ids={integration.team.organization_id},
    )
    if user is None:
        _reply(
            chat_id,
            message,
            "I don't know who you are yet. Link your PostHog account first: "
            f"open {settings.SITE_URL}/telegram/link/start/?team_id={integration.team_id} while logged in.",
        )
        return HttpResponse(status=200)

    _start_telegram_mention_workflow(integration, chat_id, message, user.id, update_id)
    return HttpResponse(status=202)
