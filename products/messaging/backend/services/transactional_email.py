"""Sends one transactional email from a message template through the workflows email pipeline."""

import hashlib
from typing import Any
from uuid import UUID

import requests
import structlog

from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import send_transactional_email as queue_transactional_email
from posthog.redis import get_client

from products.messaging.backend.facade.contracts import (
    DeliveryUnavailable,
    InvalidRecipient,
    MarketingTemplate,
    QueuedEmail,
    QuotaLimited,
    SenderUnavailable,
    SendInProgress,
    TemplateNotSendable,
)
from products.messaging.backend.models import MessageCategory, MessageTemplate
from products.messaging.backend.models.message_category import MessageCategoryType

logger = structlog.get_logger(__name__)

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_IN_FLIGHT = b"in-flight"


def _sendable_template(team_id: int, template_id: UUID) -> MessageTemplate:
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id, deleted=False)
    email = (template.content or {}).get("email")
    if template.type != "email" or not isinstance(email, dict) or not email.get("subject"):
        raise TemplateNotSendable("The template has no email subject, so it can't be sent.")
    if not (email.get("text") or email.get("html")):
        raise TemplateNotSendable("The template has no email body, so it can't be sent.")
    if template.message_category_id:
        category = MessageCategory.objects.filter(
            team_id=team_id, id=template.message_category_id, deleted=False
        ).first()
        # Transactional sends skip opt-outs, so a marketing template must never go out this way.
        if category and category.category_type == MessageCategoryType.MARKETING:
            raise MarketingTemplate(
                "The template is in a marketing category. Only transactional templates can be sent."
            )
    return template


def _sender_integration_id(team: Team, from_integration_id: int | None) -> int:
    integration_id = from_integration_id or team.workflows_config.default_email_integration_id
    integration = (
        Integration.objects.filter(team_id=team.id, kind="email", id=integration_id).first() if integration_id else None
    )
    if not integration or not integration.config.get("verified"):
        raise SenderUnavailable("No verified email sender. Verify a sending domain or pass from_integration_id.")
    return integration.id


def _email_input(template: MessageTemplate, to: str, integration_id: int) -> dict[str, Any]:
    email = template.content["email"]
    return {
        "to": {"email": to, "name": ""},
        "from": {"integrationId": integration_id},
        "replyTo": "",
        "cc": "",
        "bcc": "",
        "subject": email["subject"],
        "preheader": email.get("preheader") or "",
        "text": email.get("text") or "",
        "html": email.get("html") or "",
    }


def _idempotency_redis_key(team_id: int, idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"messaging:transactional_email:idempotency:{team_id}:{digest}"


def send_transactional_email(
    team: Team,
    template_id: UUID,
    *,
    to: str,
    distinct_id: str | None,
    message_data: dict[str, Any],
    from_integration_id: int | None = None,
    idempotency_key: str | None = None,
) -> QueuedEmail:
    # The pipeline renders the whole email input as Liquid, so a recipient address with Liquid markup
    # would be rendered against the template data instead of sent as typed.
    if "{" in to or "}" in to:
        raise InvalidRecipient("The recipient address can't contain { or }.")
    template = _sendable_template(team.id, template_id)
    integration_id = _sender_integration_id(team, from_integration_id)

    redis = get_client()
    redis_key = _idempotency_redis_key(team.id, idempotency_key) if idempotency_key else None
    if redis_key and not redis.set(redis_key, _IN_FLIGHT, nx=True, ex=IDEMPOTENCY_TTL_SECONDS):
        existing = redis.get(redis_key)
        if existing is None or existing == _IN_FLIGHT:
            raise SendInProgress("A request with this idempotency key is still in progress.")
        return QueuedEmail(message_id=existing.decode(), replayed=True)

    payload = {
        "template_name": template.name,
        "message_category_id": str(template.message_category_id) if template.message_category_id else None,
        "email": _email_input(template, to, integration_id),
        "distinct_id": distinct_id,
        "variables": message_data,
    }
    try:
        response = queue_transactional_email(team.id, str(template.id), payload)
    except (requests.ConnectionError, RuntimeError) as e:
        # The request never reached cdp-api, so nothing is queued and a retry can send.
        if redis_key:
            redis.delete(redis_key)
        logger.exception("transactional_email_queue_failed", team_id=team.id, template_id=str(template.id))
        raise DeliveryUnavailable() from e
    except Exception as e:
        # cdp-api can queue the email before the response times out. The reservation stays, so a retry
        # with the same key gets a conflict instead of a second email.
        logger.exception("transactional_email_queue_outcome_unknown", team_id=team.id, template_id=str(template.id))
        raise DeliveryUnavailable() from e

    if response.status_code != 202:
        # Only a 5xx can come after the job is queued, so only a 4xx rejection releases the reservation.
        if redis_key and response.status_code < 500:
            redis.delete(redis_key)
        if response.status_code == 429:
            raise QuotaLimited("The project is over its email quota.")
        logger.error(
            "transactional_email_queue_rejected",
            team_id=team.id,
            template_id=str(template.id),
            status_code=response.status_code,
        )
        raise DeliveryUnavailable()

    message_id = str(response.json()["invocation_id"])
    if redis_key:
        redis.set(redis_key, message_id, ex=IDEMPOTENCY_TTL_SECONDS)
    return QueuedEmail(message_id=message_id, replayed=False)
