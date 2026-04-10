"""Incoming webhook for Customer.io reporting webhooks.

Receives delivery-related events from a team's Customer.io workspace and, when the event
is an ``unsubscribed`` metric, mirrors the opt-out into PostHog's own suppression list
(``MessageRecipientPreference``). This keeps PostHog-managed campaigns from emailing
recipients who unsubscribed via Customer.io while email campaigns are being migrated
between the two systems.

Signature verification follows Customer.io's documented scheme
(https://docs.customer.io/integrations/data-out/connections/webhooks/):

    X-CIO-Signature = HMAC_SHA256(webhook_signing_secret,
                                  "v0:" + X-CIO-Timestamp + ":" + raw_body)

The raw request body must be used verbatim — parsing and re-serializing JSON subtly
changes whitespace/ordering and breaks verification.
"""

from __future__ import annotations

import hmac
import json
import time
import hashlib
import logging

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from posthog.models.integration import Integration

from products.messaging.backend.services.customerio_sync_service import (
    CUSTOMERIO_INTEGRATION_KIND,
    CustomerIOSyncConfig,
    record_inbound_unsubscribe,
)

logger = logging.getLogger(__name__)

# Reject webhook requests whose X-CIO-Timestamp is farther than this from "now" to make
# naive replay attacks harmless even if a signing secret ever leaks into a log/pcap.
MAX_TIMESTAMP_SKEW_SECONDS = 5 * 60


def _verify_signature(signing_secret: str, timestamp: str, raw_body: bytes, provided_signature: str) -> bool:
    if not (signing_secret and timestamp and provided_signature):
        return False
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts_int) > MAX_TIMESTAMP_SKEW_SECONDS:
        return False

    # "v0:<timestamp>:<raw_body>" — build as bytes so we never touch body encoding.
    mac = hmac.new(
        signing_secret.encode("utf-8"),
        b"v0:" + timestamp.encode("utf-8") + b":" + raw_body,
        hashlib.sha256,
    )
    expected = mac.hexdigest()

    # Customer.io sends the hex digest. Use compare_digest for constant-time comparison.
    return hmac.compare_digest(expected, provided_signature.strip())


def _extract_identifier(data: dict) -> str | None:
    """Find the best identifier for the unsubscribed person in an inbound payload.

    Customer.io includes a free-form ``identifiers`` object whose contents depend on the
    workspace's identifier strategy. We prefer ``email`` (matches how PostHog's suppression
    list keys rows) and fall back to ``email_address`` and ``customer_id``.
    """
    identifiers = data.get("identifiers") or {}
    for key in ("email", "cio_id", "id"):
        value = identifiers.get(key)
        if isinstance(value, str) and value:
            return value
    email_address = data.get("email_address")
    if isinstance(email_address, str) and email_address:
        return email_address
    customer_id = data.get("customer_id")
    if isinstance(customer_id, str) and customer_id:
        return customer_id
    return None


@csrf_exempt
@require_http_methods(["POST"])
def customerio_webhook(request: HttpRequest, team_id: int) -> JsonResponse:
    """Handle an incoming Customer.io reporting webhook for the given team."""
    # Find the team's Customer.io integration. We look it up directly (no auth) because
    # signature verification is what actually authenticates the request.
    integration = (
        Integration.objects.filter(team_id=team_id, kind=CUSTOMERIO_INTEGRATION_KIND).order_by("-created_at").first()
    )
    if integration is None:
        return JsonResponse({"error": "not_configured"}, status=404)

    config = CustomerIOSyncConfig(integration=integration)
    signing_secret = config.webhook_signing_secret
    if not signing_secret:
        return JsonResponse({"error": "webhook_not_configured"}, status=404)

    raw_body = request.body or b""
    timestamp = request.headers.get("X-CIO-Timestamp", "")
    signature = request.headers.get("X-CIO-Signature", "")

    if not _verify_signature(signing_secret, timestamp, raw_body, signature):
        # Intentionally generic error so we don't give an attacker any signal.
        return JsonResponse({"error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    metric = payload.get("metric")
    # Customer.io reporting webhooks send many metric types (delivered, opened, bounced,
    # clicked, …). We only care about global unsubscribes here — everything else is a 200
    # so Customer.io doesn't keep retrying it.
    if metric != "unsubscribed":
        return JsonResponse({"status": "ignored", "metric": metric})

    data = payload.get("data") or {}
    identifier = _extract_identifier(data)
    if not identifier:
        logger.warning(
            "Customer.io unsubscribe webhook did not contain a usable identifier",
            extra={"team_id": team_id, "event_id": payload.get("event_id")},
        )
        return JsonResponse({"error": "missing_identifier"}, status=400)

    try:
        record_inbound_unsubscribe(team_id=team_id, identifier=identifier)
    except Exception:
        logger.exception(
            "Failed to record Customer.io inbound unsubscribe",
            extra={"team_id": team_id, "event_id": payload.get("event_id")},
        )
        return JsonResponse({"error": "processing_failed"}, status=500)

    return JsonResponse({"status": "ok"})
