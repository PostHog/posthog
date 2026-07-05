"""Inbound webhook receiver for the PostHog Code Linear agent.

The handler stays deliberately dumb — verify, dedupe, enqueue — so Linear's delivery
deadline is never threatened by DB or GraphQL work. Everything else happens in the
``process_linear_agent_event`` Celery task.
"""

import json

from django.conf import settings
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.utils import safe_cache_add

from products.tasks.backend.logic.linear_agent.parsing import (
    HANDLED_WEBHOOK_TYPES,
    verify_linear_signature,
    webhook_timestamp_valid,
)
from products.tasks.backend.tasks import process_linear_agent_event

logger = structlog.get_logger(__name__)

# Keep dedupe keys as long as the payload staleness window so a delivery can never be
# accepted twice: inside the window the key still exists, outside it the timestamp
# check rejects the payload.
WEBHOOK_DEDUPE_TTL_SECONDS = 24 * 60 * 60


def handle_linear_agent_webhook(request: HttpRequest) -> HttpResponse:
    """Handle a Linear app webhook POST.

    Called from core's csrf-exempt ``/webhooks/linear`` route; auth is the
    HMAC signature, verified here against ``LINEAR_AGENT_WEBHOOK_SECRET``.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    secret = settings.LINEAR_AGENT_WEBHOOK_SECRET
    if not secret:
        logger.warning("linear_agent_webhook_not_configured")
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("Linear-Signature")
    if not verify_linear_signature(request.body, signature, secret):
        return HttpResponse("Invalid signature", status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    if not isinstance(payload, dict):
        return HttpResponse("Invalid JSON", status=400)

    if not webhook_timestamp_valid(payload):
        return HttpResponse("Stale webhook timestamp", status=403)

    if payload.get("type") not in HANDLED_WEBHOOK_TYPES:
        return HttpResponse(status=200)

    # Linear re-delivers on failure; `Linear-Delivery` identifies the delivery, with the
    # payload identifiers as fallback. Duplicate-task protection doesn't hinge on this —
    # the mapping's unique constraint is the real guarantee.
    delivery_id = request.headers.get("Linear-Delivery") or (
        f"{payload.get('webhookId')}:{payload.get('webhookTimestamp')}:{payload.get('action')}"
    )
    if not safe_cache_add(f"linear_agent_webhook:{delivery_id}", "1", WEBHOOK_DEDUPE_TTL_SECONDS):
        logger.info("linear_agent_webhook_duplicate_skipped", delivery_id=delivery_id)
        return HttpResponse(status=200)

    process_linear_agent_event.delay(payload=payload)
    return HttpResponse(status=202)
