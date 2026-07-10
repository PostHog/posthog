"""Inbound webhook for the dedicated Stamphog GitHub App.

This is a standalone endpoint for Stamphog's own GitHub App — it does not share the
unified ``posthog.urls.github_webhook`` fan-out. The integration layer wires the URL.
"""

import hmac
import json
import hashlib
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from products.stamphog.backend.tasks.tasks import process_pull_request_event

logger = structlog.get_logger(__name__)


def _verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Constant-time check of the ``X-Hub-Signature-256`` header (``sha256=<hex>``)."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@csrf_exempt
def stamphog_github_webhook(request: HttpRequest) -> HttpResponse:
    """Verify, filter, and enqueue an inbound Stamphog GitHub App delivery."""
    if request.method != "POST":
        return HttpResponse(status=405)

    secret = getattr(settings, "STAMPHOG_GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("stamphog_webhook_not_configured")
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_signature(request.body, signature, secret):
        return HttpResponse("Invalid signature", status=403)

    # Only pull_request drives reviews; ack everything else so GitHub stops retrying.
    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "pull_request":
        return HttpResponse(status=200)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    cast(Any, process_pull_request_event).delay(payload=payload, delivery_id=delivery_id)
    return HttpResponse(status=202)
