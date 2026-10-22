"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

import re
from email.utils import parseaddr
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

import structlog

from posthog.models.integration import Integration
from posthog.plugins.plugin_server_api import (
    reload_hog_flows_on_workers,
    send_transactional_email as run_transactional_workflow,
)

from products.messaging.backend.facade.contracts import (
    AcceptedSend,
    EmailSendCommand,
    EmailSendOutcome,
    MarketingTemplate,
    Queued,
    Rejected,
    RenderedContent,
    RenderedEmail,
    SenderNotAllowed,
    SenderNotVerified,
    SenderUnavailable,
    SendFrom,
    SendRoute,
    StoredTemplate,
    TemplateNotSendable,
    TemplateNotTransactional,
    TransactionalEmailError,
    TransactionalEmailPaused,
    Unavailable,
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

logger = structlog.get_logger(__name__)

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


def is_transactional(template: MessageTemplate) -> bool:
    return template.transactional_hog_flow_id is not None and _workflow_exists(
        template.team_id, template.transactional_hog_flow_id
    )


def check_still_sendable(template: MessageTemplate) -> None:
    """Raise when a written but unsaved template could no longer send as a transactional email."""
    # A link to a deleted workflow no longer restricts the template. The sync after the save clears it.
    if template.deleted or not is_transactional(template):
        return
    check_sendable(
        template.team_id,
        template_type=template.type,
        content=template.content,
        message_category_id=template.message_category_id,
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
    _require_workflow(team_id, template.transactional_hog_flow_id)
    return template.transactional_hog_flow_id


def _require_workflow(team_id: int, hog_flow_id: UUID) -> None:
    # The CDP service checks that the workflow is active after it looks up the idempotency key,
    # so a retry of a send that went out still replays after its workflow is paused.
    try:
        get_workflow_summary(team_id=team_id, workflow_id=str(hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalEmailPaused("The template's transactional email no longer exists.") from e


def _code_email_workflow_id(team_id: int, key: str) -> UUID:
    template_id = (
        MessageTemplate.objects.filter(team_id=team_id, key=key, deleted=False).values_list("id", flat=True).first()
    )
    if template_id is not None:
        return _transactional_workflow_id(team_id, template_id)
    hog_flow_id = _key_workflow_id(team_id, key)
    _require_workflow(team_id, hog_flow_id)
    return hog_flow_id


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
    # A concurrent first send made the key's workflow after this one looked for it, so this send uses that one.
    return keys.get(key=key).hog_flow_id


def code_send_from(team_id: int, address: str | None) -> SendFrom:
    """The verified sender a code send goes out from: the one `address` names, or the project's default."""
    name, email = parseaddr(address) if address else ("", "")
    try:
        sender = code_send_sender(team_id=team_id, email=email or None, name=name or None)
    except TransactionalEmailSenderUnavailable as e:
        if address:
            raise SenderNotAllowed(f"No verified sender in this project can send from `{email}`.") from e
        raise SenderNotVerified("The project has no verified default email sender.") from e
    return SendFrom(integration_id=sender.integration_id, email=sender.email, name=sender.name, is_default=not address)


def rendered_content(*, subject: str, html: str, text: str) -> RenderedContent:
    return RenderedContent(subject=subject, html=html, text=text or text_from_html(html))


def send_email(command: EmailSendCommand) -> EmailSendOutcome:
    if command.idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(command.idempotency_key):
        return Rejected(
            code="invalid_idempotency_key",
            detail="The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces.",
        )
    # Defense in depth: the workflow reads the recipient from an event property, which Liquid outputs as typed.
    if "{" in command.to or "}" in command.to:
        return Rejected(code="invalid_recipient", detail="The recipient address can't contain { or }.")
    try:
        hog_flow_id = _sendable_workflow_id(command.team_id, command.source)
    except TransactionalEmailError as e:
        return Rejected(code=e.code, detail=str(e))
    payload: dict[str, Any] = {
        "to": command.to,
        # The recipient is the person the send is tracked against. Without a distinct_id, the address is one.
        "distinct_id": command.distinct_id or command.to,
        "variables": dict(command.source.message_data) if isinstance(command.source, StoredTemplate) else {},
    }
    if command.idempotency_key is not None:
        # The CDP service holds the key, because only it knows whether the email was queued.
        payload["idempotency_key"] = command.idempotency_key
    if command.source.send is not None:
        payload["send"] = _send_payload(command.source.send)
    if command.route == SendRoute.SEND_EMAIL:
        # The template route sends none, so its keys keep the fingerprint they were reserved with.
        payload["route"] = command.route.value
    try:
        response = run_transactional_workflow(command.team_id, str(hog_flow_id), payload)
    except Exception:
        logger.exception("transactional_email_queue_failed", team_id=command.team_id, hog_flow_id=str(hog_flow_id))
        return Unavailable()

    if response.status_code != 202:
        if response.status_code == 400 and (refused := _failed_send_check(response)):
            return refused
        if response.status_code == 429:
            return Rejected(code="quota_limited", detail="The project is over its email quota.")
        if response.status_code == 409:
            return Rejected(
                code="idempotency_key_in_flight",
                detail="A request with this Idempotency-Key is still being processed. Retry in a few seconds.",
            )
        if response.status_code == 422:
            return Rejected(
                code="idempotency_key_reused",
                detail="This Idempotency-Key was already used for a different request. Use a new key for a new email.",
            )
        logger.error(
            "transactional_email_queue_rejected",
            team_id=command.team_id,
            hog_flow_id=str(hog_flow_id),
            status_code=response.status_code,
        )
        return Unavailable()

    body = response.json()
    return Queued(message_id=str(body["invocation_id"]), replayed=bool(body.get("replayed", False)))


# The CDP service runs these checks before it queues, and answers each with what to change.
SEND_CHECK_CODES = frozenset(
    {
        "invalid_recipient",
        "sender_not_verified",
        "sending_suspended",
        "template_paused",
        "recipient_suppressed",
        "transactional_email_paused",
    }
)


def _failed_send_check(response: Any) -> Rejected | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("code") not in SEND_CHECK_CODES:
        return None
    return Rejected(code=body["code"], detail=str(body["detail"]), why=str(body["why"]), fix=str(body["fix"]))


def _sendable_workflow_id(team_id: int, source: StoredTemplate | RenderedEmail) -> UUID:
    match source:
        case StoredTemplate(template_id=template_id):
            return _transactional_workflow_id(team_id, template_id)
        case RenderedEmail(key=key):
            return _code_email_workflow_id(team_id, key)


def _send_payload(send: AcceptedSend) -> dict[str, Any]:
    payload: dict[str, Any] = {"tracking": {"captureEngagement": send.capture_engagement}}
    if send.content is not None:
        payload["content"] = _without_empty(
            {"subject": send.content.subject, "text": send.content.text, "html": send.content.html}
        )
    if send.sender is not None:
        payload["from"] = _without_empty(
            {
                "integrationId": send.sender.integration_id,
                "email": send.sender.email,
                "name": send.sender.name,
                "isDefault": send.sender.is_default,
            }
        )
    if send.reply_to:
        payload["replyTo"] = list(send.reply_to)
    if send.cc:
        payload["cc"] = list(send.cc)
    if send.bcc:
        payload["bcc"] = list(send.bcc)
    if send.headers:
        payload["headers"] = [{"name": header.name, "value": header.value} for header in send.headers]
    if send.tags:
        payload["tags"] = [{"name": tag.name, "value": tag.value} for tag in send.tags]
    return payload


def _without_empty(fields: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in fields.items() if value}
