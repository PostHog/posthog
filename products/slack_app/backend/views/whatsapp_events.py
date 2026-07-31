"""Webhook endpoint for the central PostHog WhatsApp Business number.

Meta delivers every event for the app to a single URL, so whichever Cloud region
receives a message routes it to the region that owns the chat's binding (mirroring
the Telegram flow): a locally bound chat is handled here, an unbound one triggers a
claims probe and, when the other region claims it (or the probe fails), the original
request is proxied across with the loop header set.

Two envelope quirks vs Telegram: Meta verifies the endpoint with a GET handshake
(``hub.challenge`` echo), and a single POST can batch several messages (plus
delivery ``statuses``, which are ignored). Meta retries on non-200 with backoff.
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
from posthog.temporal.ai.whatsapp_app import WhatsAppAppMentionWorkflow, WhatsAppAppMentionWorkflowInputs
from posthog.temporal.common.client import sync_connect

from products.slack_app.backend.api import (
    REGION_PROXY_HEADER,
    _proxy_event_to_region,
    cross_region_routing_enabled,
    other_region_domain,
    was_proxied,
)
from products.slack_app.backend.feature_flags import is_whatsapp_app_enabled
from products.slack_app.backend.providers import ChatProviderError, WhatsAppChatProvider
from products.slack_app.backend.services.region_auth import (
    REGION_SIGNATURE_HEADER,
    REGION_TIMESTAMP_HEADER,
    region_claims_secret,
    sign_region_request,
)
from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError, WhatsAppBotClient, whatsapp_config
from products.slack_app.backend.services.whatsapp_link import (
    find_linked_whatsapp_user,
    handle_link_redemption,
    link_command_code,
)

logger = structlog.get_logger(__name__)

_MESSAGE_DEDUP_TTL_SECONDS = 24 * 60 * 60
_CHAT_CLAIMS_CACHE_TTL_SECONDS = 60
_CHAT_CLAIMS_TIMEOUT_SECONDS = (1, 1)


def _reply(wa_id: str, message_id: str | None, text: str) -> None:
    """Best-effort reply; the webhook must ack regardless."""
    try:
        WhatsAppBotClient().send_message(to=wa_id, text=text, reply_to_message_id=message_id)
    except WhatsAppApiError as e:
        logger.warning("slack_app_whatsapp_webhook_reply_failed", wa_id=wa_id, error=str(e))


def _does_other_region_claim_chat(wa_id: str, *, incoming_host: str) -> bool | None:
    """WhatsApp flavor of the workspace-claims probe; definitive answers cached."""
    cache_key = f"whatsapp_app:chat_claims:{wa_id}"
    cached = cache.get(cache_key)
    if isinstance(cached, bool):
        return cached

    target_domain = other_region_domain(incoming_host)
    scheme = "http" if settings.DEBUG else "https"
    target_url = f"{scheme}://{target_domain}/chat/whatsapp/workspace/claims/"
    body = json.dumps({"workspace_id": wa_id, "kinds": ["whatsapp"]}).encode("utf-8")
    signature, ts = sign_region_request(body, region_claims_secret("whatsapp"))

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
        logger.warning("slack_app_whatsapp_chat_claims_failed", target_url=target_url, error=str(exc))
        return None
    if response.status_code != 200:
        logger.warning(
            "slack_app_whatsapp_chat_claims_non_200", target_url=target_url, status_code=response.status_code
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


def _start_whatsapp_mention_workflow(integration: Integration, message: dict[str, Any], user_id: int) -> None:
    wamid = str(message.get("id") or "")
    inputs = WhatsAppAppMentionWorkflowInputs(
        integration_id=integration.id,
        wa_id=str(message.get("from") or ""),
        message=message,
        user_id=user_id,
        message_wamid=wamid,
    )
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            WhatsAppAppMentionWorkflow.run,
            inputs,
            # wamids are globally unique, so redeliveries collapse onto the same
            # execution (second dedup layer after the cache guard).
            id=f"whatsapp-app-mention-{integration.id}:{wamid}",
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )


def _extract_messages(data: dict[str, Any]) -> list[tuple[dict[str, Any], str | None]]:
    """Flatten the entry/changes envelope into (message, sender profile name) pairs."""
    results: list[tuple[dict[str, Any], str | None]] = []
    for entry in data.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            names = {
                str(contact.get("wa_id") or ""): ((contact.get("profile") or {}).get("name"))
                for contact in value.get("contacts") or []
                if isinstance(contact, dict)
            }
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                results.append((message, names.get(str(message.get("from") or ""))))
    return results


def _handle_message(request: HttpRequest, message: dict[str, Any], profile_name: str | None) -> bool:
    """Process one inbound message; returns True when it must be proxied cross-region."""
    wa_id = str(message.get("from") or "")
    wamid = str(message.get("id") or "")
    text = str(((message.get("text") or {}).get("body")) or "")
    # Text DMs only: no media in v1, and anything group-scoped (the Groups API
    # stamps a group id) is out of surface.
    if not wa_id or not wamid or message.get("type") != "text" or not text or message.get("group_id"):
        return False
    if not cache.add(f"whatsapp_app:message:{wamid}", "1", timeout=_MESSAGE_DEDUP_TTL_SECONDS):
        return False

    # The link command works even in unbound chats — it's how a chat GETS bound.
    if link_command_code(text) is not None:
        _reply(wa_id, wamid, handle_link_redemption(wa_id=wa_id, profile_name=profile_name, text=text))
        return False

    integration = (
        Integration.objects.filter(kind="whatsapp", integration_id=wa_id)
        .select_related("team", "team__organization")
        .first()
    )
    if integration is None:
        if cross_region_routing_enabled() and not was_proxied(request):
            claimed = _does_other_region_claim_chat(wa_id, incoming_host=request.get_host())
            if claimed is not False:
                # Claimed there, or unknown: optimistic proxy, like the other providers.
                return True
        if was_proxied(request):
            # The owning region would have had the binding; a proxied unbound message
            # is a dead end — dropping it avoids a proxy loop.
            return False
        _reply(
            wa_id,
            wamid,
            "This chat isn't connected to a PostHog project yet. "
            f"Open {settings.SITE_URL}/whatsapp/link/start/?team_id=<your project id> while logged in to PostHog.",
        )
        return False

    if not is_whatsapp_app_enabled(integration):
        # Flagged-off chats stay completely dark — no reply, no workflow.
        return False

    user = find_linked_whatsapp_user(wa_id=wa_id, candidate_org_ids={integration.team.organization_id})
    if user is None:
        _reply(
            wa_id,
            wamid,
            "I don't know who you are yet. Link your PostHog account first: "
            f"open {settings.SITE_URL}/whatsapp/link/start/?team_id={integration.team_id} while logged in.",
        )
        return False

    _start_whatsapp_mention_workflow(integration, message, user.id)
    return False


@csrf_exempt
def whatsapp_event_handler(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        # Meta's webhook verification handshake: echo hub.challenge back when the
        # verify token matches. An unconfigured token rejects everything.
        expected = str(whatsapp_config()["WHATSAPP_APP_VERIFY_TOKEN"] or "")
        if expected and request.GET.get("hub.mode") == "subscribe" and request.GET.get("hub.verify_token") == expected:
            return HttpResponse(request.GET.get("hub.challenge") or "")
        return HttpResponse("Invalid request", status=403)

    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        WhatsAppChatProvider.validate_webhook(request)
    except ChatProviderError as e:
        logger.warning("slack_app_whatsapp_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    to_proxy: list[str] = []
    for message, profile_name in _extract_messages(data):
        if _handle_message(request, message, profile_name):
            to_proxy.append(str(message.get("id") or ""))

    if to_proxy:
        # One proxy call carries the whole original batch; each region keeps only
        # what's bound to it (proxied unbound messages are dropped, not re-proxied).
        if _proxy_event_to_region(request, other_region_domain(request.get_host())) is None:
            # Unmark the proxied messages so Meta's retry isn't swallowed by dedup.
            for wamid in to_proxy:
                cache.delete(f"whatsapp_app:message:{wamid}")
            return HttpResponse(status=502)

    return HttpResponse(status=200)
