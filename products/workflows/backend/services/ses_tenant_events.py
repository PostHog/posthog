"""AWS SES tenant reputation events, delivered via EventBridge → SNS HTTPS subscription.

Events are treated as change signals only — the handler never trusts the payload's state; it
enqueues a sync that reads the authoritative tenant state from the SES API. That makes duplicate,
reordered, or partially-shaped events harmless.

The SNS message signature and the topic-ARN allowlist are checked by the ingress transport, which
reads the allowlist from `WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS`. AWS-side wiring: an EventBridge
rule on `source = aws.ses` for the tenant detail-types, targeting an SNS topic with an HTTPS
subscription to this endpoint.
"""

import re
import json
from collections.abc import Mapping
from typing import Any

import requests
import structlog

from posthog.ingress.contracts import WebhookDelivery
from posthog.ingress.verify.sns_signature import is_valid_sns_url

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


def _confirm_subscription(message: Mapping[str, Any]) -> None:
    """Call back the SubscribeURL AWS sent, which completes the SNS subscription handshake."""
    subscribe_url = message.get("SubscribeURL")
    if not isinstance(subscribe_url, str) or not is_valid_sns_url(subscribe_url):
        # Dropped rather than raised, like an unusable notification payload: a redelivery carries
        # the same URL, so retrying it can never confirm the subscription.
        logger.warning("ses_tenant_events_webhook_invalid_subscribe_url", topic=message.get("TopicArn"))
        return
    # A failed callback to AWS's own URL is raised rather than dropped: it leaves the subscription
    # unconfirmed, and raising costs the request its receipt, because the SNS incarnation sets a
    # retry status, so SNS sends the handshake again.
    requests.get(subscribe_url, timeout=5).raise_for_status()
    logger.info("ses_tenant_events_webhook_subscription_confirmed", topic=message.get("TopicArn"))


def _handle_notification(message: Mapping[str, Any]) -> None:
    """Enqueue a tenant-state sync for the team the EventBridge event names.

    Every unusable payload is dropped rather than raised, because a redelivery would carry the
    same unusable payload.
    """
    try:
        event = json.loads(message.get("Message", ""))
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(event, dict) or event.get("source") != "aws.ses":
        return

    team_id = _extract_team_id(event)
    if team_id is None:
        logger.warning("ses_tenant_events_webhook_no_tenant", detail_type=event.get("detail-type"))
        return

    # Logged because the only other line on this path is the failure one, which leaves a handled
    # delivery and an ignored one looking identical from outside: both answer 2xx.
    logger.info("ses_tenant_events_webhook_accepted", team_id=team_id, detail_type=event.get("detail-type"))
    # Ack fast; the sync fetches authoritative state and sends any transition emails.
    sync_ses_tenant_state_task.delay(team_id)


def handle_ses_tenant_event(delivery: WebhookDelivery) -> None:
    """One SNS delivery: the subscription handshake, or a tenant reputation event."""
    if delivery.event_type == "SubscriptionConfirmation":
        _confirm_subscription(delivery.payload)
    elif delivery.event_type == "Notification":
        _handle_notification(delivery.payload)
