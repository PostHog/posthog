"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

import re
from collections.abc import Callable
from email.utils import parseaddr
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from django.db import IntegrityError, transaction

import structlog

from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import (
    reload_hog_flows_on_workers,
    send_accepted_transactional_email,
    send_transactional_email as run_transactional_workflow,
)

from products.messaging.backend.facade.contracts import (
    CodeEmail,
    DeliveryUnavailable,
    IdempotencyKeyInFlight,
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    InvalidRecipient,
    MarketingTemplate,
    QueuedEmail,
    QuotaLimited,
    RecipientSuppressed,
    RecipientUnreachable,
    SenderNotVerified,
    SenderUnavailable,
    SendingPaused,
    SendingSuspended,
    TemplateNotSendable,
    TemplateNotTransactional,
    TransactionalEmailError,
    TransactionalEmailPaused,
)
from products.messaging.backend.models import MessageCategory, MessageTemplate, TransactionalEmailKey
from products.messaging.backend.models.message_category import MessageCategoryType
from products.messaging.backend.models.transactional_email_key import TRANSACTIONAL_EMAIL_KEY_CONSTRAINT
from products.messaging.backend.services.html_text import text_from_html
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary
from products.workflows.backend.facade.transactional_emails import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderUnavailable,
    code_send_sender,
    create_code_email_workflow,
    create_transactional_email_workflow,
    resolve_transactional_email_sender,
    update_transactional_email_workflow,
)

if TYPE_CHECKING:
    import requests

logger = structlog.get_logger(__name__)

# The CDP service names the reason it refused a send in the body's `error`. A retry of the same request gets the
# same refusal, so each of these reaches the caller as a 4xx and not as a retryable 503.
PIPELINE_REFUSALS: dict[str, tuple[type[TransactionalEmailError], str]] = {
    "quota_limited": (QuotaLimited, "The project is over its email quota."),
    "idempotency_key_in_flight": (
        IdempotencyKeyInFlight,
        "A request with this Idempotency-Key is still being processed. Retry in a few seconds.",
    ),
    "idempotency_key_reused": (
        IdempotencyKeyReused,
        "This Idempotency-Key was already used for a different request. Use a new key for a new email.",
    ),
    "sending_suspended": (
        SendingSuspended,
        "Email sending is suspended for this project. Check the Reputation tab in Workflows, or contact support.",
    ),
    "sending_paused": (
        SendingPaused,
        "Email sending is paused for this transactional email because of its bounce or complaint rate. "
        "Check the Reputation tab in Workflows.",
    ),
    "recipient_suppressed": (
        RecipientSuppressed,
        "The recipient is on this project's suppression list after a hard bounce or a spam complaint, so the "
        "email can't be sent. Remove the address from the suppression list if it can receive email again.",
    ),
    "recipient_unreachable": (
        RecipientUnreachable,
        "The recipient's address can't receive email: it isn't a valid address, or its domain has no mail servers, "
        "so the email would bounce. Check the address for a typo.",
    ),
    "not_sendable": (TransactionalEmailPaused, "The template's transactional email isn't active."),
}

IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,255}")


def check_sendable(team_id: int, *, template_type: str, content: dict, message_category_id: UUID | None) -> None:
    """Raise when a template with these fields can't be a transactional email."""
    email = (content or {}).get("email")
    if template_type != "email" or not isinstance(email, dict) or not email.get("subject"):
        raise TemplateNotSendable("The template has no email subject, so it can't be sent.")
    if not (email.get("text") or email.get("html")):
        raise TemplateNotSendable("The template has no email body, so it can't be sent.")
    if message_category_id:
        # A deleted category still classifies the template, and the category field accepts one.
        category = MessageCategory.objects.filter(team_id=team_id, id=message_category_id).first()
        # Transactional sends skip opt-outs, so a marketing template must never go out this way.
        if category and category.category_type == MessageCategoryType.MARKETING:
            raise MarketingTemplate(
                "The template is in a marketing category. Only transactional templates can be sent."
            )


# An address longer than this can't be delivered, and the bound keeps the pattern below fast.
SENDER_ADDRESS_MAX_LENGTH = 254
# Matches the send path, which ignores a custom address that fails these checks and sends from the sender's own.
SENDER_ADDRESS_PATTERN = re.compile(r'^[^\s@"<>,;]+@[^\s@"<>,;]+\.[^\s@"<>,;]+$')


def sender_address_error(team_id: int, sender: dict[str, Any]) -> str | None:
    """Why a custom sender address can't send, or None. A templated address is only known at send time."""
    address = (sender.get("email") or "").strip()
    if not address or "{{" in address or "{%" in address:
        return None
    if len(address) > SENDER_ADDRESS_MAX_LENGTH:
        return f"Use an address of at most {SENDER_ADDRESS_MAX_LENGTH} characters."
    if not SENDER_ADDRESS_PATTERN.match(address):
        return "Enter one email address, like hello@example.com."
    integration_id = sender.get("integrationId")
    # Without a sender there is no domain to check against. The sender field rejects that case on its own.
    if integration_id is None:
        return None
    config = (
        Integration.objects.filter(team_id=team_id, kind="email", id=integration_id)
        .values_list("config", flat=True)
        .first()
        or {}
    )
    domain = (config.get("domain") or (config.get("email") or "").partition("@")[2]).lower()
    if domain and address.partition("@")[2].lower() != domain:
        return f"Use an address on {domain}, the domain this sender is verified for."
    return None


def _template_sender(email: dict[str, Any]) -> dict[str, Any]:
    # Templates saved before senders existed hold an empty string here.
    sender = email.get("from")
    return sender if isinstance(sender, dict) else {}


def _content(template: MessageTemplate) -> TransactionalEmailContent:
    email = template.content["email"]
    sender = _template_sender(email)
    return TransactionalEmailContent(
        message_template_id=template.id,
        name=template.name,
        subject=email["subject"],
        preheader=email.get("preheader") or "",
        html=email.get("html") or "",
        text=email.get("text") or "",
        # Templates made transactional before they stored a sender keep their workflow's sender.
        from_integration_id=sender.get("integrationId"),
        message_category_id=template.message_category_id,
        sensitive=template.sensitive,
        from_email=sender.get("email") or "",
        from_name=sender.get("name") or "",
        reply_to=email.get("replyTo") or "",
    )


def make_transactional(
    team_id: int, template_id: UUID, *, user_id: int | None, from_integration_id: int | None
) -> UUID:
    """Create the template's workflow and link it, and return the workflow's id. A template that is already
    transactional keeps the workflow it has."""
    with transaction.atomic():
        # The row lock keeps two concurrent calls from creating two workflows.
        template = MessageTemplate.objects.select_for_update().get(team_id=team_id, id=template_id, deleted=False)
        if template.transactional_hog_flow_id and _workflow_exists(team_id, template.transactional_hog_flow_id):
            return template.transactional_hog_flow_id
        check_sendable(
            team_id,
            template_type=template.type,
            content=template.content,
            message_category_id=template.message_category_id,
        )
        email = template.content["email"]
        sender = _template_sender(email)
        try:
            # The template keeps the sender it is made transactional with, so the editor shows it and later
            # saves send from it.
            sender_id = resolve_transactional_email_sender(team_id, from_integration_id or sender.get("integrationId"))
            sender = {**sender, "integrationId": sender_id}
            # A custom address set for one sender can't send from a sender on another domain.
            if address_error := sender_address_error(team_id, sender):
                raise TemplateNotSendable(address_error)
            template.content = {**template.content, "email": {**email, "from": sender}}
            hog_flow_id = create_transactional_email_workflow(
                team_id=team_id, user_id=user_id, content=_content(template)
            )
        except TransactionalEmailSenderUnavailable as e:
            raise SenderUnavailable(
                "No verified email sender. Verify a sending domain or pass from_integration_id."
            ) from e
        template.transactional_hog_flow_id = hog_flow_id
        template.save(update_fields=["content", "transactional_hog_flow_id", "updated_at"])
    return hog_flow_id


def _workflow_exists(team_id: int, hog_flow_id: UUID) -> bool:
    try:
        get_workflow_summary(team_id=team_id, workflow_id=str(hog_flow_id))
    except WorkflowNotFound:
        return False
    return True


def lock_transactional_workflow_id(team_id: int, template_id: UUID) -> UUID | None:
    """Lock the template row for the rest of the transaction and return its workflow id. Holding the lock
    keeps make_transactional from linking a workflow between this read and the update that follows."""
    return (
        MessageTemplate.objects.select_for_update()
        .filter(team_id=team_id, id=template_id)
        .values_list("transactional_hog_flow_id", flat=True)
        .get()
    )


def check_transactional_update(template_id: UUID, team_id: int, fields: dict[str, Any]) -> None:
    """Raise when an update would leave a transactional template unable to send. `fields` are validated
    serializer fields, where `message_category` holds a category id."""
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id)
    if not template.transactional_hog_flow_id or fields.get("deleted"):
        return
    # A link to a deleted workflow no longer restricts the template. The sync after the update clears it.
    if not _workflow_exists(team_id, template.transactional_hog_flow_id):
        return
    check_sendable(
        team_id,
        template_type=fields.get("type", template.type),
        content=fields.get("content", template.content),
        message_category_id=fields.get("message_category", template.message_category_id),
    )


def _reload_workers(team_id: int, hog_flow_id: UUID) -> None:
    # The edit is already committed, so a failed reload must not fail the request. Workers still pick up the
    # new version when their cache expires.
    try:
        reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[str(hog_flow_id)])
    except Exception:
        logger.exception("transactional_email_worker_reload_failed", team_id=team_id, hog_flow_id=str(hog_flow_id))


def sync_transactional_workflow(team_id: int, template_id: UUID, *, user_id: int | None) -> None:
    """Write the template's current content as a new version of its workflow, if it has one."""
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id)
    if not template.transactional_hog_flow_id or template.deleted:
        return
    hog_flow_id = template.transactional_hog_flow_id
    if not _workflow_exists(team_id, hog_flow_id):
        # Someone deleted the workflow. The template stops being transactional and can be made so again.
        MessageTemplate.objects.filter(team_id=team_id, id=template_id).update(transactional_hog_flow_id=None)
        return
    try:
        update_transactional_email_workflow(
            team_id=team_id,
            user_id=user_id,
            hog_flow_id=hog_flow_id,
            content=_content(template),
        )
        # The save already told the workers to reload, but before the caller's transaction committed, so a
        # worker can cache the old version. This reload runs once the new version is visible.
        transaction.on_commit(lambda: _reload_workers(team_id, hog_flow_id))
    except WorkflowNotFound:
        # Deleted between the check above and the update.
        MessageTemplate.objects.filter(team_id=team_id, id=template_id).update(transactional_hog_flow_id=None)
    except TransactionalEmailContentInvalid as e:
        raise TemplateNotSendable("The template needs a subject and a body to send.") from e
    except TransactionalEmailSenderUnavailable as e:
        raise SenderUnavailable("No verified email sender. Verify a sending domain first.") from e


def _transactional_workflow_id(team_id: int, template_id: UUID) -> UUID:
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id, deleted=False)
    if not template.transactional_hog_flow_id:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    # A category's type can change after the template was made transactional.
    check_sendable(
        team_id,
        template_type=template.type,
        content=template.content,
        message_category_id=template.message_category_id,
    )
    _require_active(team_id, template.transactional_hog_flow_id)
    return template.transactional_hog_flow_id


def _require_active(team_id: int, hog_flow_id: UUID) -> None:
    try:
        workflow = get_workflow_summary(team_id=team_id, workflow_id=str(hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalEmailPaused("The template's transactional email no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalEmailPaused("The template's transactional email isn't active.")


def _code_email_workflow_id(team_id: int, key: str) -> UUID:
    template_id = _template_id_for_key(team_id, key)
    if template_id is not None:
        return _transactional_workflow_id(team_id, template_id)
    hog_flow_id = _key_workflow_id(team_id, key)
    _require_active(team_id, hog_flow_id)
    return hog_flow_id


def _template_id_for_key(team_id: int, key: str) -> UUID | None:
    return MessageTemplate.objects.filter(team_id=team_id, key=key, deleted=False).values_list("id", flat=True).first()


def known_key(team_id: int, key: str) -> TransactionalEmailKey | None:
    return TransactionalEmailKey.objects.for_team(team_id).filter(key=key).first()


def _key_workflow_id(team_id: int, key: str) -> UUID:
    keys = TransactionalEmailKey.objects.for_team(team_id)
    known = known_key(team_id, key)
    if known is not None:
        if _workflow_exists(team_id, known.hog_flow_id):
            return known.hog_flow_id
        known.delete()
    try:
        with transaction.atomic():
            hog_flow_id = create_code_email_workflow(team_id=team_id, key=key)
            keys.create(team_id=team_id, key=key, hog_flow_id=hog_flow_id)
        return hog_flow_id
    except IntegrityError as error:
        if TRANSACTIONAL_EMAIL_KEY_CONSTRAINT not in str(error):
            raise
    return keys.get(key=key).hog_flow_id


def require_code_email_access(
    team_id: int,
    key: str,
    *,
    require_workflow_editor: Callable[[UUID], None],
    require_workflow_create: Callable[[], None],
) -> None:
    template = MessageTemplate.objects.filter(team_id=team_id, key=key, deleted=False).first()
    if template is not None:
        if template.transactional_hog_flow_id is not None:
            require_workflow_editor(template.transactional_hog_flow_id)
        return
    hog_flow_id = (
        TransactionalEmailKey.objects.for_team(team_id).filter(key=key).values_list("hog_flow_id", flat=True).first()
    )
    if hog_flow_id is not None and _workflow_exists(team_id, hog_flow_id):
        require_workflow_editor(hog_flow_id)
    else:
        require_workflow_create()


def send_transactional_email(
    team: Team,
    template_id: UUID,
    *,
    to: str,
    distinct_id: str | None,
    message_data: dict[str, Any],
    idempotency_key: str | None = None,
    timeout: float = 10,
) -> QueuedEmail:
    _check_send_request(to, idempotency_key)
    hog_flow_id = _transactional_workflow_id(team.id, template_id)
    payload = _send_payload(to, distinct_id, message_data, idempotency_key)
    return _queue(team.id, hog_flow_id, payload, run_transactional_workflow, timeout=timeout)


def send_code_email(
    team: Team,
    email: CodeEmail,
    *,
    to: str,
    distinct_id: str | None,
    idempotency_key: str | None = None,
) -> QueuedEmail:
    _check_send_request(to, idempotency_key)
    accepted_send = _accepted_send(team.id, email)
    hog_flow_id = _code_email_workflow_id(team.id, email.key)
    payload = {
        **_send_payload(to, distinct_id, {}, idempotency_key),
        "send": accepted_send,
        "requested_from": email.sender,
    }
    return _queue(team.id, hog_flow_id, payload, send_accepted_transactional_email)


def _check_send_request(to: str, idempotency_key: str | None) -> None:
    if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise InvalidIdempotencyKey(
            "The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces."
        )
    # Defense in depth: the workflow reads the recipient from an event property, which Liquid outputs as typed.
    if "{" in to or "}" in to:
        raise InvalidRecipient("The recipient address can't contain { or }.")


def _send_payload(
    to: str, distinct_id: str | None, message_data: dict[str, Any], idempotency_key: str | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": to,
        # The recipient is the person the send is tracked against. Without a distinct_id, the address is one.
        "distinct_id": distinct_id or to,
        "variables": message_data,
    }
    if idempotency_key is not None:
        # The CDP service holds the key, because only it knows whether the email was queued.
        payload["idempotency_key"] = idempotency_key
    return payload


def _accepted_send(team_id: int, email: CodeEmail) -> dict[str, Any]:
    return {
        "content": _without_empty(
            {"subject": email.subject, "html": email.html, "text": email.text or text_from_html(email.html)}
        ),
        "from": _without_empty(_code_send_sender(team_id, email.sender)),
        "replyTo": list(email.reply_to),
        "tracking": {"captureEngagement": email.capture_engagement},
    }


def _code_send_sender(team_id: int, address: str | None) -> dict[str, Any]:
    name, email = parseaddr(address) if address else ("", "")
    try:
        sender = code_send_sender(team_id=team_id, email=email or None, name=name or None)
    except TransactionalEmailSenderUnavailable as e:
        if address:
            raise SenderNotVerified(f"No verified sender in this project can send from `{email}`.") from e
        raise SenderNotVerified("The project has no verified default email sender.") from e
    return {"integrationId": sender.integration_id, "email": sender.email, "name": sender.name}


def _without_empty(fields: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in fields.items() if value}


class _PipelinePost(Protocol):
    def __call__(
        self, team_id: int, hog_flow_id: str, payload: dict, *, timeout: float = ...
    ) -> "requests.Response": ...


def _queue(
    team_id: int,
    hog_flow_id: UUID,
    payload: dict[str, Any],
    post: _PipelinePost,
    *,
    timeout: float = 10,
) -> QueuedEmail:
    try:
        response = post(team_id, str(hog_flow_id), payload, timeout=timeout)
    except Exception as e:
        logger.exception("transactional_email_queue_failed", team_id=team_id, hog_flow_id=str(hog_flow_id))
        raise DeliveryUnavailable() from e

    if response.status_code != 202:
        refusal = PIPELINE_REFUSALS.get(_refusal_code(response) or "")
        if refusal is not None:
            error_class, message = refusal
            raise error_class(message)
        logger.error(
            "transactional_email_queue_rejected",
            team_id=team_id,
            hog_flow_id=str(hog_flow_id),
            status_code=response.status_code,
        )
        raise DeliveryUnavailable()

    body = response.json()
    return QueuedEmail(message_id=str(body["invocation_id"]), replayed=bool(body.get("replayed", False)))


def _refusal_code(response: "requests.Response") -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None
