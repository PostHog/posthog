"""
Inbound webhook for AWS SES tenant reputation events, delivered via EventBridge → SNS HTTPS
subscription. Events are treated as change signals only — the handler never trusts the payload's
state; it enqueues a sync that reads the authoritative tenant state from the SES API. That makes
duplicate, reordered, or partially-shaped events harmless.

Authentication is the SNS message signature (proves "from AWS") plus a topic-ARN allowlist
(proves "from our topic"). AWS-side wiring: an EventBridge rule on `source = aws.ses` for the
tenant detail-types, targeting an SNS topic with an HTTPS subscription to this endpoint.
"""

import re
import json
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import requests
import structlog

from products.workflows.backend.services.sns_verification import is_valid_sns_url, verify_sns_message
from products.workflows.backend.tasks.ses_tenant_state import sync_ses_tenant_state_task

logger = structlog.get_logger(__name__)

_TENANT_TEAM_RE = re.compile(r"\bteam-(\d+)\b")


def _extract_team_id(event: dict[str, Any]) -> int | None:
    """Pull the `team-<id>` tenant name out of an EventBridge event, wherever AWS put it."""
    detail = event.get("detail") or {}
    candidates: list[Any] = [
        detail.get("tenantName"),
        detail.get("tenant-name"),
        detail.get("reputationEntityReference"),
    ]
    resources = event.get("resources")
    if isinstance(resources, list):
        candidates.extend(resources)
    for candidate in candidates:
        if isinstance(candidate, str) and (match := _TENANT_TEAM_RE.search(candidate)):
            return int(match.group(1))
    return None


@csrf_exempt
def ses_tenant_events_webhook(request: HttpRequest) -> HttpResponse:
    """Verify an SNS delivery and enqueue a tenant-state sync for the affected team."""
    if request.method != "POST":
        return HttpResponse(status=405)

    allowed_topics = {arn for arn in settings.WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS if arn}
    if not allowed_topics:
        # Unconfigured means the endpoint doesn't exist yet as far as callers are concerned. 404
        # rather than 500 so that probes of a public URL can't flood error logs, and warning
        # rather than error for the same reason.
        logger.warning("ses_tenant_events_webhook_not_configured")
        return HttpResponse("Not found", status=404)

    try:
        # RecursionError: deeply nested JSON from an unauthenticated caller must 400, not 500.
        message = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        return HttpResponse("Invalid payload", status=400)
    if not isinstance(message, dict):
        return HttpResponse("Invalid payload", status=400)

    if message.get("TopicArn") not in allowed_topics:
        logger.warning("ses_tenant_events_webhook_unknown_topic", topic=message.get("TopicArn"))
        return HttpResponse("Unknown topic", status=403)
    if not verify_sns_message(message):
        logger.warning("ses_tenant_events_webhook_invalid_signature", message_id=message.get("MessageId"))
        return HttpResponse("Invalid signature", status=403)

    message_type = message.get("Type")
    if message_type == "SubscriptionConfirmation":
        subscribe_url = message.get("SubscribeURL")
        if not isinstance(subscribe_url, str) or not is_valid_sns_url(subscribe_url):
            return HttpResponse("Invalid subscribe URL", status=400)
        try:
            requests.get(subscribe_url, timeout=5).raise_for_status()
        except requests.RequestException:
            # Non-2xx makes SNS retry the confirmation later.
            logger.exception("ses_tenant_events_webhook_subscription_confirm_failed", topic=message.get("TopicArn"))
            return HttpResponse("Subscription confirmation failed", status=502)
        logger.info("ses_tenant_events_webhook_subscription_confirmed", topic=message.get("TopicArn"))
        return HttpResponse(status=200)

    if message_type != "Notification":
        # UnsubscribeConfirmation and anything unknown: ack so SNS stops retrying.
        return HttpResponse(status=200)

    try:
        event = json.loads(message.get("Message", ""))
    except (json.JSONDecodeError, TypeError):
        return HttpResponse(status=200)
    if not isinstance(event, dict) or event.get("source") != "aws.ses":
        return HttpResponse(status=200)

    team_id = _extract_team_id(event)
    if team_id is None:
        logger.warning("ses_tenant_events_webhook_no_tenant", detail_type=event.get("detail-type"))
        return HttpResponse(status=200)

    # Logged because the only other line on this path is the failure one, which leaves a handled
    # delivery and an ignored one looking identical from outside: both answer 2xx.
    logger.info("ses_tenant_events_webhook_accepted", team_id=team_id, detail_type=event.get("detail-type"))
    # Ack fast; the sync fetches authoritative state and sends any transition emails.
    sync_ses_tenant_state_task.delay(team_id)
    return HttpResponse(status=202)
