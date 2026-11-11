"""Transactional push notifications: a push template made sendable over the API. Each one is backed by a workflow
that runs once per send, so sends get the workflow's metrics, run history and versions."""

from typing import Any
from uuid import UUID

import structlog

from posthog.models.team import Team
from posthog.plugins.plugin_server_api import send_transactional_push as run_transactional_push_workflow

from products.messaging.backend.facade.contracts import (
    DeliveryUnavailable,
    IdempotencyKeyInFlight,
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    InvalidRequest,
    QueuedEmail,
    QuotaLimited,
    TemplateNotSendable,
    TemplateNotTransactional,
    TransactionalEmailError,
    TransactionalPushPaused,
)
from products.messaging.backend.services.transactional_email import (
    IDEMPOTENCY_KEY_PATTERN,
    TransactionalTemplate,
    check_sendable,
)
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary

logger = structlog.get_logger(__name__)

PUSH_REFUSALS: dict[str, tuple[type[TransactionalEmailError], str]] = {
    "quota_limited": (QuotaLimited, "The project is over its quota for push notifications."),
    "idempotency_key_in_flight": (
        IdempotencyKeyInFlight,
        "A request with this Idempotency-Key is still being processed. Retry in a few seconds.",
    ),
    "idempotency_key_reused": (
        IdempotencyKeyReused,
        "This Idempotency-Key was already used for a different request. Use a new key for a new notification.",
    ),
    "not_sendable": (
        TransactionalPushPaused,
        "This push notification's workflow isn't active or no longer only sends a push. Turn it back on, or "
        "save the template again to restore it.",
    ),
    "invalid_request": (
        InvalidRequest,
        "The push pipeline couldn't accept a field of this notification, so it wasn't sent. Check the distinct "
        "ID and message data, then send it again.",
    ),
}


def send_transactional_push(
    team: Team,
    template: TransactionalTemplate,
    *,
    distinct_id: str,
    message_data: dict[str, Any],
    idempotency_key: str | None = None,
    timeout: float = 10,
) -> QueuedEmail:
    """Queue one push notification from a transactional push template to every device of one person."""
    if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise InvalidIdempotencyKey(
            "The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces."
        )
    hog_flow_id = _transactional_push_workflow_id(team.id, template)
    payload: dict[str, Any] = {"distinct_id": distinct_id, "variables": message_data}
    if idempotency_key is not None:
        # The CDP service holds the key, because only it knows whether the push was queued.
        payload["idempotency_key"] = idempotency_key
    try:
        response = run_transactional_push_workflow(team.id, str(hog_flow_id), payload, timeout=timeout)
    except Exception as e:
        logger.exception("transactional_push_queue_failed", team_id=team.id, hog_flow_id=str(hog_flow_id))
        raise DeliveryUnavailable() from e
    if response.status_code != 202:
        refusal_code = _refusal_code(response)
        refusal = PUSH_REFUSALS.get(refusal_code or "")
        if refusal is None or refusal[0] is InvalidRequest:
            logger.error(
                "transactional_push_queue_rejected",
                team_id=team.id,
                hog_flow_id=str(hog_flow_id),
                status_code=response.status_code,
                refusal_code=refusal_code,
            )
        if refusal is None:
            raise DeliveryUnavailable()
        error_class, message = refusal
        raise error_class(message)
    body = response.json()
    return QueuedEmail(message_id=str(body["invocation_id"]), replayed=bool(body.get("replayed", False)))


def _transactional_push_workflow_id(team_id: int, template: TransactionalTemplate) -> UUID:
    if template.type != "push":
        raise TemplateNotSendable("The template isn't a push template. Send it with the email API instead.")
    if not template.transactional_hog_flow_id:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    # A category's type can change after the template was made transactional.
    check_sendable(
        team_id,
        template_type=template.type,
        content=template.content,
        message_category_id=template.message_category_id,
    )
    try:
        workflow = get_workflow_summary(team_id=team_id, workflow_id=str(template.transactional_hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalPushPaused("This push notification's workflow no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalPushPaused("This push notification's workflow isn't active. Turn it back on to send.")
    return template.transactional_hog_flow_id


def _refusal_code(response: Any) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None
