"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

import re
import json
import time
import dataclasses
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parseaddr
from functools import cache
from typing import Any, Literal, Protocol, TypeGuard
from uuid import UUID

from django.db import transaction

import requests
import structlog
from prometheus_client import Counter, Histogram

from posthog.helpers.email_utils import email_domain
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import (
    prepare_transactional_email_attachment_uploads,
    send_accepted_transactional_email,
    send_accepted_transactional_email_batch,
    send_transactional_email as run_transactional_workflow,
    send_transactional_email_batch as run_transactional_workflow_batch,
)

from products.messaging.backend.facade.contracts import (
    AttachmentNotUploaded,
    AttachmentsRefused,
    AttachmentUploadRequest,
    AttachmentUploadSlot,
    AttachmentUploadTarget,
    BatchRecipient,
    BatchTooLarge,
    BatchUnavailable,
    CodeEmail,
    ContentTooLarge,
    DeliveryUnavailable,
    EmailAttachment,
    EmailBatchSent,
    EmailNotQueued,
    EmailTracking,
    FieldNotAccepted,
    IdempotencyKeyInFlight,
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    InvalidRecipient,
    InvalidRequest,
    MarketingTemplate,
    MessageTooLarge,
    NamedSenderNotVerified,
    PresentAttachment,
    QueuedEmail,
    QueuedEmailStatus,
    QuotaLimited,
    RecipientSuppressed,
    RecipientUnreachable,
    SandboxFieldsUnsupported,
    SandboxRecipientNotMember,
    SandboxSenderNotAvailable,
    SenderNotVerified,
    SenderRequired,
    SenderUnavailable,
    SendingPaused,
    SendingSuspended,
    SendWarning,
    SendWarningCode,
    SensitiveTemplate,
    TemplateNotSendable,
    TemplateNotTransactional,
    TooManyKeys,
    TransactionalEmailError,
    TransactionalEmailPaused,
    UploadQuotaExceeded,
)
from products.messaging.backend.models import FirstCodeSend, MessageCategory, MessageTemplate, TransactionalEmailKey
from products.messaging.backend.models.message_category import MessageCategoryType
from products.messaging.backend.models.transactional_email_key import lock_team_keys as _lock_team_keys
from products.messaging.backend.services.code_email_source import source_detection_enabled
from products.messaging.backend.services.html_text import text_from_html
from products.messaging.backend.services.transactional_email_status import keyed_message_id
from products.messaging.backend.tasks import detect_code_email_source_task
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary
from products.workflows.backend.facade.sandbox_email import provision_sandbox_sender
from products.workflows.backend.facade.transactional_emails import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderRequired,
    TransactionalEmailSenderUnavailable,
    code_send_sandbox_sender_available,
    code_send_sender_id,
    create_code_email_workflow,
    create_transactional_email_workflow,
    resolve_transactional_email_sender,
    sending_domain_setup,
    update_transactional_email_workflow,
)
from products.workflows.backend.facade.transactional_push import (
    TransactionalPushChannelUnavailable,
    TransactionalPushContent,
    TransactionalPushContentInvalid,
    create_transactional_push_workflow,
    update_transactional_push_workflow,
)

logger = structlog.get_logger(__name__)

CDP_SEND_DURATION = Histogram(
    "messaging_transactional_email_cdp_request_duration_seconds",
    "Time for the CDP service to answer a request to queue one transactional email, including failed requests.",
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 7.5, 10, 15),
)
CDP_SEND_RESULTS = Counter(
    "messaging_transactional_email_cdp_requests_total",
    "Requests to the CDP service to queue one transactional email, by result: success (202), the HTTP status class "
    "of any other answer, timeout, connection_error, or error.",
    labelnames=["result"],
)
CDP_BATCH_DURATION = Histogram(
    "messaging_transactional_email_cdp_batch_request_duration_seconds",
    "Time for the CDP service to answer a request to queue a batch of transactional emails, including failed requests.",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 7.5, 10, 15, 20, 25, 30),
)
CDP_BATCH_RESULTS = Counter(
    "messaging_transactional_email_cdp_batch_requests_total",
    "Requests to the CDP service to queue a batch of transactional emails, by result: success (200 with one answer "
    "per recipient), malformed (200 with any other body), the HTTP status class of any other answer, timeout, "
    "connection_error, or error.",
    labelnames=["result"],
)
SANDBOX_FALLBACKS = Counter(
    "messaging_transactional_email_sandbox_fallback_total",
    "Code sends from projects without a verified sender, by outcome: sandbox (the pipeline queued a first send from "
    "the sandbox sender; replays are not counted), recipient_not_member (the pipeline refused the recipient, who is "
    "not a member of the organization), or fields_unsupported (refused before the request because the sandbox sender "
    "cannot send a field the request set).",
    labelnames=["outcome"],
)


TransactionalEmailStage = Literal[
    "auth",
    "permissions",
    "throttle",
    "validation",
    "feature_flag",
    "template_lookup",
    "workflow_access",
    "workflow_lookup",
    "cdp_call",
    "usage_event",
    "total",
]
STAGE_DURATION = Histogram(
    "messaging_transactional_email_stage_duration_seconds",
    "Time one transactional email send request spends in each stage, including requests that fail in that stage: "
    "auth, permissions and throttle (DRF's checks), validation (the request body), feature_flag, template_lookup, "
    "workflow_access (the caller's editor access to the workflow), workflow_lookup (the template and workflow "
    "checks before the send), cdp_call (the same time as messaging_transactional_email_cdp_request_duration_seconds), "
    "usage_event, and total (the DRF view from start to response).",
    labelnames=["stage"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15),
)


def observe_transactional_email_stage(stage: TransactionalEmailStage, seconds: float) -> None:
    STAGE_DURATION.labels(stage=stage).observe(seconds)


@contextmanager
def transactional_email_stage(stage: TransactionalEmailStage) -> Iterator[None]:
    started_at = time.monotonic()
    try:
        yield
    finally:
        observe_transactional_email_stage(stage, time.monotonic() - started_at)


def _cdp_error_result(error: Exception) -> str:
    # ConnectTimeout is both a Timeout and a ConnectionError, so the timeout check goes first.
    if isinstance(error, requests.Timeout):
        return "timeout"
    if isinstance(error, requests.ConnectionError):
        return "connection_error"
    return "error"


def _cdp_response_result(status_code: int) -> str:
    return "success" if status_code == 202 else f"{status_code // 100}xx"


def _observe_cdp_call(seconds: float) -> None:
    # Both histograms get the same value, so the stage breakdown and the CDP request metric can't disagree.
    CDP_SEND_DURATION.observe(seconds)
    observe_transactional_email_stage("cdp_call", seconds)


SANDBOX_FIELDS_UNSUPPORTED = (
    "This project has no verified sending domain, so this email would go out from the PostHog test sender, which "
    "can't send `cc`, `bcc` or `attachments`. Remove those fields, or verify a sending domain at {setup_url}."
)

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
    "not_sendable": (TransactionalEmailPaused, "This email's workflow isn't active. Turn it back on to send."),
    "invalid_request": (
        InvalidRequest,
        "The email pipeline couldn't accept a field of this email, so it wasn't sent. Check the addresses and "
        "fields, then send it again.",
    ),
    "sandbox_recipient_not_member": (
        SandboxRecipientNotMember,
        "The PostHog test sender only sends to members of your organization until this project verifies a sending "
        "domain, so this email wasn't sent. Verify a sending domain at {setup_url} to send to anyone.",
    ),
    "sandbox_fields_unsupported": (SandboxFieldsUnsupported, SANDBOX_FIELDS_UNSUPPORTED),
    "sandbox_sender_unavailable": (
        SandboxSenderNotAvailable,
        "The PostHog test sender isn't available for this organization, so this email wasn't sent. Verify a sending "
        "domain at {setup_url} to send email.",
    ),
    "batch_unavailable": (
        BatchUnavailable,
        "Batch sends aren't available for this project yet, so PostHog didn't send any of these emails. Send each "
        "email on its own instead.",
    ),
}

BATCH_REFUSALS = frozenset(
    {
        "batch_unavailable",
        "quota_limited",
        "sending_suspended",
        "sending_paused",
        "not_sendable",
        "sandbox_sender_unavailable",
    }
)
RECIPIENT_REFUSALS = frozenset(
    {"idempotency_key_reused", "recipient_suppressed", "recipient_unreachable", "sandbox_recipient_not_member"}
)
BATCH_INVALID_RECIPIENT = (
    "PostHog can't send to this recipient as given. Check its `to`, `distinct_id` and `message_data`, then send it "
    "again."
)

SANDBOX_SENDER_KIND = "email_sandbox"
SANDBOX_SENDER_WARNING = (
    "This email goes out from the PostHog test sender, because this project has no verified sending domain. The "
    "PostHog test sender only sends to members of your organization. Verify a sending domain to send to anyone from "
    "your own address."
)
BATCH_SANDBOX_SENDER_WARNING = (
    "PostHog accepted these emails to send from the PostHog test sender, because this project has no verified "
    "sending domain. The PostHog test sender only sends to members of your organization. Verify a sending domain to "
    "send to anyone from your own address."
)

FILES_REFUSALS: dict[str, tuple[str, str, str]] = {
    "workflow_shape_not_supported": (
        "This email's workflow can't send files, so PostHog didn't send the email.",
        "A send with files needs a workflow with a trigger, one transactional email step, then an exit.",
        "Send files through a workflow that has a trigger, then one transactional email step, then an exit, or "
        "send this email without files.",
    ),
    "workflow_can_wait": (
        "This email's workflow can hold a send, so PostHog didn't send the email with its files.",
        "A step or a sending rate limit in this workflow can hold the send, so its files could expire before the "
        "email goes out.",
        "Send files through a workflow whose transactional email step follows the trigger directly and has no "
        "sending rate limit, or send this email without files.",
    ),
    "email_render_limit_exceeded": (
        "PostHog couldn't check the size of this email with its files, so it didn't send it.",
        "Rendering this email's template went over a limit on time or length, so the size of the email with its "
        "files couldn't be checked.",
        "Simplify the email's template, or send this email without files.",
    ),
    "utm_value_too_long": (
        "A UTM value in this email's workflow is too long, so PostHog didn't send the email with its files.",
        "A UTM value is longer than 1,000 characters, so the size of this email with its files couldn't be checked.",
        "Shorten each UTM value of the email step to 1,000 characters or fewer, or send this email without files.",
    ),
    "email_body_too_many_tags": (
        "This email's template has too many Liquid tags, so PostHog didn't send the email with its files.",
        "The email step has more than 10,000 Liquid tags, so the size of this email with its files couldn't be "
        "checked.",
        "Use 10,000 Liquid tags or fewer in the email step, or send this email without files.",
    ),
}

IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,255}")


def is_idempotency_key(value: str) -> bool:
    return IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is not None


BATCH_SHARED_MAX_BYTES = 256 * 1024
BATCH_TIMEOUT_SECONDS = 30

TRANSACTIONAL_EMAIL_KEY_LIMIT = 1000


def check_sendable(team_id: int, *, template_type: str, content: dict, message_category_id: UUID | None) -> None:
    """Raise when a template with these fields can't be a transactional email or push notification."""
    if template_type == "push":
        _check_push_sendable(content)
    else:
        _check_email_sendable(template_type, content)
    if message_category_id:
        # A deleted category still classifies the template, and the category field accepts one.
        category = MessageCategory.objects.filter(team_id=team_id, id=message_category_id).first()
        # Transactional sends skip opt-outs, so a marketing template must never go out this way.
        if category and category.category_type == MessageCategoryType.MARKETING:
            raise MarketingTemplate(
                "The template is in a marketing category. Only transactional templates can be sent."
            )


def _check_email_sendable(template_type: str, content: dict) -> None:
    email = (content or {}).get("email")
    if template_type != "email" or not isinstance(email, dict) or not email.get("subject"):
        raise TemplateNotSendable("The template has no email subject, so it can't be sent.")
    if not (email.get("text") or email.get("html")):
        raise TemplateNotSendable("The template has no email body, so it can't be sent.")


def _check_push_sendable(content: dict) -> None:
    push = (content or {}).get("push")
    if not isinstance(push, dict) or not (push.get("title") or "").strip():
        raise TemplateNotSendable("The template has no push title, so it can't be sent.")
    if not (push.get("body") or "").strip():
        raise TemplateNotSendable("The template has no push body, so it can't be sent.")
    if not push.get("channels"):
        raise TemplateNotSendable("The template has no push channel. Choose a Firebase or APNs app to send through.")


# An address longer than this can't be delivered, and the bound keeps the pattern below fast.
SENDER_ADDRESS_MAX_LENGTH = 254
# Matches the send path, which ignores a custom address that fails these checks and sends from the sender's own.
SENDER_ADDRESS_PATTERN = re.compile(r'^[^\s@"<>,;]+@[^\s@"<>,;]+\.[^\s@"<>,;]+$')
PIPELINE_ADDRESS_PATTERN = re.compile(
    r"[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+"
)


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
    try:
        config = IntegrationManager.email.credentials.get(team_id, integration_id).config or {}
    except IntegrationNotFound:
        config = {}
    domain = (config.get("domain") or email_domain(config.get("email") or "") or "").lower()
    if domain and (email_domain(address) or "").lower() != domain:
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


def _push_content(template: MessageTemplate) -> TransactionalPushContent:
    push = template.content["push"]
    return TransactionalPushContent(
        message_template_id=template.id,
        name=template.name,
        title=push.get("title") or "",
        body=push.get("body") or "",
        channel_ids=tuple(push.get("channels") or ()),
        message_category_id=template.message_category_id,
        image=push.get("image") or "",
        link=push.get("link") or "",
        data=push.get("data") or {},
        sensitive=template.sensitive,
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
        if template.type == "push":
            hog_flow_id = _create_push_workflow(team_id, template, user_id=user_id)
            template.transactional_hog_flow_id = hog_flow_id
            template.save(update_fields=["transactional_hog_flow_id", "updated_at"])
            return hog_flow_id
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


def _create_push_workflow(team_id: int, template: MessageTemplate, *, user_id: int | None) -> UUID:
    try:
        return create_transactional_push_workflow(team_id=team_id, user_id=user_id, content=_push_content(template))
    except TransactionalPushChannelUnavailable as e:
        raise TemplateNotSendable("A push channel of this template no longer exists. Choose another one.") from e
    except TransactionalPushContentInvalid as e:
        raise TemplateNotSendable("The template needs a title, a body and a push channel to send.") from e


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
    if fields.get("type", template.type) != template.type:
        raise TemplateNotSendable("A transactional template can't change between email and push.")
    check_sendable(
        team_id,
        template_type=template.type,
        content=fields.get("content", template.content),
        message_category_id=fields.get("message_category", template.message_category_id),
    )


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
        if template.type == "push":
            update_transactional_push_workflow(
                team_id=team_id, user_id=user_id, hog_flow_id=hog_flow_id, content=_push_content(template)
            )
        else:
            update_transactional_email_workflow(
                team_id=team_id,
                user_id=user_id,
                hog_flow_id=hog_flow_id,
                content=_content(template),
            )
    except WorkflowNotFound:
        # Deleted between the check above and the update.
        MessageTemplate.objects.filter(team_id=team_id, id=template_id).update(transactional_hog_flow_id=None)
    except TransactionalEmailContentInvalid as e:
        raise TemplateNotSendable("The template needs a subject and a body to send.") from e
    except TransactionalPushContentInvalid as e:
        raise TemplateNotSendable("The template needs a title, a body and a push channel to send.") from e
    except TransactionalPushChannelUnavailable as e:
        raise TemplateNotSendable("A push channel of this template no longer exists. Choose another one.") from e
    except TransactionalEmailSenderUnavailable as e:
        raise SenderUnavailable("No verified email sender. Verify a sending domain first.") from e


class TransactionalTemplate(Protocol):
    """The template fields a send reads. A caller that already loaded the template passes it in."""

    @property
    def id(self) -> UUID: ...

    @property
    def type(self) -> str: ...

    @property
    def content(self) -> dict[str, Any]: ...

    @property
    def message_category_id(self) -> UUID | None: ...

    @property
    def transactional_hog_flow_id(self) -> UUID | None: ...


def _transactional_workflow_id(team_id: int, template: TransactionalTemplate) -> UUID:
    hog_flow_id = _sendable_workflow_id(team_id, template)
    _require_active(team_id, hog_flow_id)
    return hog_flow_id


def _sendable_workflow_id(team_id: int, template: TransactionalTemplate) -> UUID:
    if template.type != "email":
        raise TemplateNotSendable("The template isn't an email template. Send it with the push API instead.")
    if not template.transactional_hog_flow_id:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    # A category's type can change after the template was made transactional.
    check_sendable(
        team_id,
        template_type=template.type,
        content=template.content,
        message_category_id=template.message_category_id,
    )
    return template.transactional_hog_flow_id


def _require_active(team_id: int, hog_flow_id: UUID) -> None:
    try:
        workflow = get_workflow_summary(team_id=team_id, workflow_id=str(hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalEmailPaused("This email's workflow no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalEmailPaused("This email's workflow isn't active. Turn it back on to send.")


def _code_email_workflow_id(team_id: int, key: str, sensitive: bool | None) -> UUID:
    hog_flow_id = _code_workflow_id(team_id, key, sensitive)
    _require_active(team_id, hog_flow_id)
    return hog_flow_id


def _code_workflow_id(team_id: int, key: str, sensitive: bool | None) -> UUID:
    template = _template_for_key(team_id, key)
    if template is None:
        hog_flow_id = _key_workflow_id(team_id, key)
        if hog_flow_id is not None:
            return hog_flow_id
        template = _template_for_key(team_id, key)
    if template is None:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    return _template_workflow_id(team_id, template, sensitive)


def _template_workflow_id(team_id: int, template: MessageTemplate, sensitive: bool | None) -> UUID:
    if sensitive is False and template.sensitive:
        raise SensitiveTemplate(
            "This email's template is marked sensitive, so `sensitive` can't be false. "
            "Leave `sensitive` out, or unmark the template."
        )
    return _sendable_workflow_id(team_id, template)


def _template_for_key(team_id: int, key: str) -> MessageTemplate | None:
    return MessageTemplate.objects.filter(team_id=team_id, key=key, deleted=False).first()


def known_key(team_id: int, key: str) -> TransactionalEmailKey | None:
    return TransactionalEmailKey.objects.for_team(team_id, canonical=True).filter(key=key).first()


def _key_workflow_id(team_id: int, key: str) -> UUID | None:
    """The code email workflow for `key`, made on its first send. None when a template took the key while this send
    waited for the lock, such as one a template import created."""
    known = known_key(team_id, key)
    if known is not None and _workflow_exists(team_id, known.hog_flow_id):
        return known.hog_flow_id
    with transaction.atomic():
        _lock_team_keys(team_id)
        known = known_key(team_id, key)
        if known is not None:
            if _workflow_exists(team_id, known.hog_flow_id):
                return known.hog_flow_id
            known.delete()
        if _template_for_key(team_id, key) is not None:
            return None
        keys = TransactionalEmailKey.objects.for_team(team_id, canonical=True)
        if keys.count() >= TRANSACTIONAL_EMAIL_KEY_LIMIT:
            raise TooManyKeys(
                f"This project has reached its limit of {TRANSACTIONAL_EMAIL_KEY_LIMIT} template keys, so it can't "
                "send under a new one. Use one template_key for each type of email, such as `order-shipped`, and "
                "reuse it for every recipient."
            )
        hog_flow_id = create_code_email_workflow(team_id=team_id, key=key)
        key_id = str(keys.create(team_id=team_id, key=key, hog_flow_id=hog_flow_id).id)
        transaction.on_commit(lambda: _queue_source_detection(team_id, key_id), robust=True)
        return hog_flow_id


def _queue_source_detection(team_id: int, key_id: str) -> None:
    # After commit and local-only, so a send never waits on the flag service while it holds the team's key lock.
    # Publishing only while the flag is on keeps the task off the queue until workers that know it are live.
    if source_detection_enabled(team_id, only_locally=True):
        detect_code_email_source_task.apply_async(args=(team_id, key_id), retry=False)


def report_first_code_send(team_id: int, capture: Callable[[], bool]) -> None:
    _, claimed = FirstCodeSend.objects.for_team(team_id).get_or_create(defaults={"team_id": team_id})
    if not claimed:
        return
    captured = False
    try:
        captured = capture()
    finally:
        if not captured:
            FirstCodeSend.objects.for_team(team_id).delete()


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
        TransactionalEmailKey.objects.for_team(team_id, canonical=True)
        .filter(key=key)
        .values_list("hog_flow_id", flat=True)
        .first()
    )
    if hog_flow_id is not None and _workflow_exists(team_id, hog_flow_id):
        require_workflow_editor(hog_flow_id)
    else:
        require_workflow_create()


def send_transactional_email(
    team: Team,
    template: UUID | TransactionalTemplate,
    *,
    to: str,
    distinct_id: str | None,
    message_data: dict[str, Any],
    idempotency_key: str | None = None,
    scheduled_at: datetime | None = None,
    timeout: float = 10,
) -> QueuedEmail:
    _check_send_request(to, idempotency_key)
    with transactional_email_stage("workflow_lookup"):
        # A template passed in must be one of the team's templates that is not deleted, as this lookup returns.
        if isinstance(template, UUID):
            model = MessageTemplate.objects.get(team_id=team.id, id=template, deleted=False)
            hog_flow_id = _transactional_workflow_id(team.id, model)
        else:
            hog_flow_id = _transactional_workflow_id(team.id, template)
    payload = _send_payload(to, distinct_id, message_data, idempotency_key, scheduled_at=scheduled_at)
    return _queue(team.id, hog_flow_id, payload, run_transactional_workflow, timeout=timeout)


def send_code_email(
    team: Team,
    email: CodeEmail,
    *,
    to: str,
    distinct_id: str | None,
    idempotency_key: str | None = None,
    scheduled_at: datetime | None = None,
) -> QueuedEmail:
    _check_send_request(to, idempotency_key, (*email.cc, *email.bcc))
    with transactional_email_stage("workflow_lookup"):
        accepted_send, sandbox_warning = _accepted_send(team, email)
        hog_flow_id = _code_email_workflow_id(team.id, email.key, email.sensitive)
    payload = {**_send_payload(to, distinct_id, {}, idempotency_key, scheduled_at=scheduled_at), "send": accepted_send}
    return _queue(team.id, hog_flow_id, payload, send_accepted_transactional_email, sandbox_warning=sandbox_warning)


def check_email_batch(
    recipients: Sequence[BatchRecipient], *, message_data: dict[str, Any] | None = None, email: CodeEmail | None = None
) -> tuple[BatchRecipient, ...]:
    if not _within_batch_shared_limit(message_data if email is None else email):
        raise ContentTooLarge(
            f"The content or `message_data` that a batch sends to every recipient can be at most "
            f"{BATCH_SHARED_MAX_BYTES // 1024} KiB. Send larger emails one at a time."
        )
    return tuple(_checked_recipient(recipient) for recipient in recipients)


def send_email_batch(
    team: Team,
    template: TransactionalTemplate,
    recipients: Sequence[BatchRecipient],
    *,
    message_data: dict[str, Any],
) -> EmailBatchSent:
    with transactional_email_stage("workflow_lookup"):
        hog_flow_id = _sendable_workflow_id(team.id, template)
    return _queue_batch(team.id, hog_flow_id, {"variables": message_data}, recipients, run_transactional_workflow_batch)


def send_code_email_batch(team: Team, email: CodeEmail, recipients: Sequence[BatchRecipient]) -> EmailBatchSent:
    with transactional_email_stage("workflow_lookup"):
        accepted_send, fallback_warning = _accepted_send(team, email)
        hog_flow_id = _code_workflow_id(team.id, email.key, email.sensitive)
    return _queue_batch(
        team.id,
        hog_flow_id,
        {"send": accepted_send},
        recipients,
        send_accepted_transactional_email_batch,
        sandbox_ignored=_fields_the_sandbox_ignores(email) if fallback_warning is not None else (),
    )


def _within_batch_shared_limit(shared: dict[str, Any] | CodeEmail | None) -> bool:
    if not isinstance(shared, CodeEmail):
        return _encoded_size(shared or {}) <= BATCH_SHARED_MAX_BYTES
    if _encoded_size([shared.subject, shared.html, shared.text]) > BATCH_SHARED_MAX_BYTES:
        return False
    return _encoded_size(_accepted_content(shared)) <= BATCH_SHARED_MAX_BYTES


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode(errors="surrogatepass"))


def _checked_recipient(recipient: BatchRecipient) -> BatchRecipient:
    if recipient.refusal is not None:
        return recipient
    try:
        _check_send_request(recipient.to, recipient.idempotency_key)
    except InvalidRecipient as e:
        return dataclasses.replace(recipient, refusal=e)
    return recipient


def _check_send_request(to: str, idempotency_key: str | None, copies: tuple[str, ...] = ()) -> None:
    if idempotency_key is not None and not is_idempotency_key(idempotency_key):
        raise InvalidIdempotencyKey(
            "The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces."
        )
    # Defense in depth: the workflow reads the recipient from an event property, which Liquid outputs as typed.
    if "{" in to or "}" in to:
        raise InvalidRecipient("The recipient address can't contain { or }.")
    if any("{" in address or "}" in address for address in copies):
        raise InvalidRecipient("A `cc` or `bcc` address can't contain { or }.")


def _send_payload(
    to: str,
    distinct_id: str | None,
    message_data: dict[str, Any],
    idempotency_key: str | None,
    *,
    scheduled_at: datetime | None = None,
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
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return payload


def _accepted_send(team: Team, email: CodeEmail) -> tuple[dict[str, Any], SendWarning | None]:
    sender, sandbox_warning = _code_send_sender(team, email)
    accepted: dict[str, Any] = {
        "content": _accepted_content(email),
        "from": _without_empty(sender),
        "tracking": _accepted_tracking(email.tracking),
    }
    if email.sensitive is not None:
        accepted["sensitive"] = email.sensitive
    if email.reply_to and sandbox_warning is None:
        accepted["replyTo"] = list(email.reply_to)
    if email.cc:
        accepted["cc"] = list(email.cc)
    if email.bcc:
        accepted["bcc"] = list(email.bcc)
    if email.attachments:
        accepted["attachments"] = [_accepted_attachment(attachment) for attachment in email.attachments]
    return accepted, sandbox_warning


def _accepted_content(email: CodeEmail) -> dict[str, str]:
    return _without_empty(
        {"subject": email.subject, "html": email.html, "text": email.text or text_from_html(email.html)}
    )


def _accepted_tracking(tracking: EmailTracking) -> dict[str, bool]:
    accepted = {"captureEngagement": tracking.engagement}
    if not tracking.opens:
        accepted["opens"] = False
    if tracking.clicks is not None:
        accepted["clicks"] = tracking.clicks
    return accepted


def _accepted_attachment(attachment: EmailAttachment) -> dict[str, str]:
    return _without_empty(
        {
            "sha256": attachment.sha256,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "content_id": attachment.content_id,
        }
    )


def _code_send_sender(team: Team, email: CodeEmail) -> tuple[dict[str, Any], SendWarning | None]:
    name, address = parseaddr(email.sender) if email.sender else ("", "")
    try:
        sender_id = code_send_sender_id(team_id=team.id, email=address or None)
    except TransactionalEmailSenderRequired as e:
        raise SenderRequired(
            "This project has more than one verified sender and no default sender. Send `from` to choose one."
        ) from e
    except TransactionalEmailSenderUnavailable as e:
        if not code_send_sandbox_sender_available(team):
            if email.sender:
                raise NamedSenderNotVerified(f"No verified sender in this project can send from `{address}`.") from e
            raise SenderNotVerified("This project has no verified email sender. Verify a sender domain first.") from e
        if field := _field_the_sandbox_sender_cannot_send(email):
            SANDBOX_FALLBACKS.labels(outcome="fields_unsupported").inc()
            setup_url = sending_domain_setup(team.id).setup_url
            raise SandboxFieldsUnsupported(SANDBOX_FIELDS_UNSUPPORTED.format(setup_url=setup_url), attr=field) from e
        sandbox_sender_id = provision_sandbox_sender(team, None).id
        logger.info("transactional_email_sandbox_sender_fallback", team_id=team.id, key=email.key)
        return {"integrationId": sandbox_sender_id}, _sandbox_sender_warning(
            team.id, _fields_the_sandbox_ignores(email)
        )
    return {"integrationId": sender_id, "email": address, "name": name}, None


def _field_the_sandbox_sender_cannot_send(email: CodeEmail) -> str | None:
    fields = {"cc": email.cc, "bcc": email.bcc, "attachments": email.attachments}
    return next((field for field, value in fields.items() if value), None)


def _fields_the_sandbox_ignores(email: CodeEmail) -> tuple[str, ...]:
    return tuple(field for field, value in (("from", email.sender), ("reply_to", email.reply_to)) if value)


def _without_empty(fields: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in fields.items() if value}


class _PipelinePost(Protocol):
    def __call__(self, team_id: int, hog_flow_id: str, payload: dict, *, timeout: float = ...) -> requests.Response: ...


def _queue(
    team_id: int,
    hog_flow_id: UUID,
    payload: dict[str, Any],
    post: _PipelinePost,
    *,
    timeout: float = 10,
    sandbox_warning: SendWarning | None = None,
) -> QueuedEmail:
    started_at = time.monotonic()
    try:
        response = post(team_id, str(hog_flow_id), payload, timeout=timeout)
    except Exception as e:
        _observe_cdp_call(time.monotonic() - started_at)
        CDP_SEND_RESULTS.labels(result=_cdp_error_result(e)).inc()
        logger.exception("transactional_email_queue_failed", team_id=team_id, hog_flow_id=str(hog_flow_id))
        raise DeliveryUnavailable() from e
    _observe_cdp_call(time.monotonic() - started_at)
    CDP_SEND_RESULTS.labels(result=_cdp_response_result(response.status_code)).inc()

    answer = _answer(response)
    refusal_code = _refusal_code(answer)
    if (payload.get("send") or {}).get("attachments") and (
        attachment_refusal := _attachment_refusal(refusal_code, answer)
    ):
        raise attachment_refusal
    if response.status_code == 413:
        raise ContentTooLarge(
            "The email is larger than PostHog can send. Make its content or data smaller, and link to "
            "large images and files instead of embedding them."
        )
    if response.status_code != 202:
        if sandbox_warning is not None and refusal_code == "sandbox_recipient_not_member":
            SANDBOX_FALLBACKS.labels(outcome="recipient_not_member").inc()
        unknown_field = _send_field_an_older_pipeline_refused(refusal_code) if response.status_code == 400 else None
        if unknown_field is not None:
            logger.warning(
                "transactional_email_field_not_accepted",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                field=unknown_field,
            )
            raise FieldNotAccepted(unknown_field)
        refusal = PIPELINE_REFUSALS.get(refusal_code or "")
        if refusal is None and response.status_code == 400:
            refusal = PIPELINE_REFUSALS["invalid_request"]
        if refusal is None or refusal[0] is InvalidRequest:
            logger.error(
                "transactional_email_queue_rejected",
                team_id=team_id,
                hog_flow_id=str(hog_flow_id),
                status_code=response.status_code,
                refusal_code=refusal_code,
            )
        if refusal is None:
            raise DeliveryUnavailable()
        error_class, message = refusal
        if "{setup_url}" in message:
            setup_url = sandbox_warning.setup_url if sandbox_warning else sending_domain_setup(team_id).setup_url
            message = message.format(setup_url=setup_url)
        error = error_class(message)
        error.attachment_bytes = _attachment_bytes(answer)
        raise error

    sent_from_sandbox = answer.get("sender_kind") == SANDBOX_SENDER_KIND
    replayed = bool(answer.get("replayed", False))
    if sandbox_warning is not None and not replayed:
        SANDBOX_FALLBACKS.labels(outcome="sandbox").inc()
    return QueuedEmail(
        message_id=str(answer["invocation_id"]),
        replayed=replayed,
        attachment_bytes=_attachment_bytes(answer),
        warnings=(sandbox_warning,) if sandbox_warning and sent_from_sandbox else (),
        sent_from_sandbox=sent_from_sandbox or (sandbox_warning is not None and not replayed),
        **_schedule(answer),
    )


def _queue_batch(
    team_id: int,
    hog_flow_id: UUID,
    shared: dict[str, Any],
    recipients: Sequence[BatchRecipient],
    post: _PipelinePost,
    *,
    sandbox_ignored: tuple[str, ...] = (),
) -> EmailBatchSent:
    sent = [recipient for recipient in recipients if recipient.refusal is None]
    payload = {**shared, "recipients": [_batch_recipient_payload(recipient) for recipient in sent]}
    answers = iter(_batch_answers(team_id, hog_flow_id, payload, sent, post) if sent else ())
    results = tuple(
        _refused_recipient(team_id, recipient, recipient.refusal) if recipient.refusal is not None else next(answers)
        for recipient in recipients
    )
    from_sandbox = any(isinstance(result, QueuedEmail) and result.sent_from_sandbox for result in results)
    warnings = (
        (_sandbox_sender_warning(team_id, sandbox_ignored, message=BATCH_SANDBOX_SENDER_WARNING),)
        if from_sandbox
        else ()
    )
    return EmailBatchSent(results=results, warnings=warnings)


def _refused_recipient(
    team_id: int, recipient: BatchRecipient, error: TransactionalEmailError | DeliveryUnavailable
) -> EmailNotQueued:
    return EmailNotQueued(message_id=str(keyed_message_id(team_id, recipient.idempotency_key)), error=error)


def _batch_recipient_payload(recipient: BatchRecipient) -> dict[str, Any]:
    payload = _send_payload(recipient.to, recipient.distinct_id, recipient.message_data, recipient.idempotency_key)
    if not payload["variables"]:
        del payload["variables"]
    return payload


def _batch_answers(
    team_id: int, hog_flow_id: UUID, payload: dict[str, Any], recipients: Sequence[BatchRecipient], post: _PipelinePost
) -> tuple[QueuedEmail | EmailNotQueued, ...]:
    started_at = time.monotonic()
    try:
        response = post(team_id, str(hog_flow_id), payload, timeout=BATCH_TIMEOUT_SECONDS)
    except Exception as e:
        CDP_BATCH_DURATION.observe(time.monotonic() - started_at)
        CDP_BATCH_RESULTS.labels(result=_cdp_error_result(e)).inc()
        logger.exception("transactional_email_batch_queue_failed", team_id=team_id, hog_flow_id=str(hog_flow_id))
        raise DeliveryUnavailable() from e
    CDP_BATCH_DURATION.observe(time.monotonic() - started_at)
    answer = _answer(response)
    answered = answer.get("results")
    if response.status_code == 200 and _answers_each(answered, recipients):
        CDP_BATCH_RESULTS.labels(result="success").inc()
        setup_url = cache(lambda: sending_domain_setup(team_id).setup_url)
        return tuple(
            _recipient_result(team_id, recipient, result["status"], result["body"], setup_url)
            for recipient, result in zip(recipients, answered)
        )
    CDP_BATCH_RESULTS.labels(
        result="malformed" if response.status_code == 200 else f"{response.status_code // 100}xx"
    ).inc()
    refusal_code = _refusal_code(answer)
    if response.status_code == 413:
        raise BatchTooLarge()
    if response.status_code == 400 and refusal_code == "sandbox_fields_unsupported":
        raise InvalidRequest(SANDBOX_FIELDS_UNSUPPORTED.format(setup_url=sending_domain_setup(team_id).setup_url))
    if 400 <= response.status_code < 500 and refusal_code in BATCH_REFUSALS:
        raise _pipeline_refusal(refusal_code, lambda: sending_domain_setup(team_id).setup_url)
    logger.error(
        "transactional_email_batch_queue_rejected",
        team_id=team_id,
        hog_flow_id=str(hog_flow_id),
        status_code=response.status_code,
        refusal_code=refusal_code if refusal_code in PIPELINE_REFUSALS else None,
    )
    if response.status_code == 400:
        raise _pipeline_refusal("invalid_request", lambda: sending_domain_setup(team_id).setup_url)
    raise DeliveryUnavailable()


def _answers_each(answered: Any, recipients: Sequence[BatchRecipient]) -> TypeGuard[list[dict[str, Any]]]:
    return (
        isinstance(answered, list)
        and len(answered) == len(recipients)
        and all(
            isinstance(result, dict) and type(result.get("status")) is int and isinstance(result.get("body"), dict)
            for result in answered
        )
    )


def _recipient_result(
    team_id: int,
    recipient: BatchRecipient,
    status_code: int,
    body: dict[str, Any],
    setup_url: Callable[[], str],
) -> QueuedEmail | EmailNotQueued:
    message_id = str(keyed_message_id(team_id, recipient.idempotency_key))
    if status_code == 202:
        from_sandbox = body.get("sender_kind") == SANDBOX_SENDER_KIND
        replayed = body.get("replayed") is True
        if from_sandbox and not replayed:
            SANDBOX_FALLBACKS.labels(outcome="sandbox").inc()
        return QueuedEmail(message_id=message_id, replayed=replayed, sent_from_sandbox=from_sandbox)
    refusal_code = _refusal_code(body)
    error: TransactionalEmailError | DeliveryUnavailable
    if status_code == 413:
        error = ContentTooLarge(
            "The email is larger than PostHog can send. Make its content or data smaller, and link to large "
            "images and files instead of embedding them."
        )
    elif status_code == 400:
        error = (
            _pipeline_refusal("invalid_request", setup_url)
            if refusal_code == "invalid_request"
            else InvalidRecipient(BATCH_INVALID_RECIPIENT)
        )
    elif status_code == 422 and refusal_code in RECIPIENT_REFUSALS:
        if refusal_code == "sandbox_recipient_not_member":
            SANDBOX_FALLBACKS.labels(outcome="recipient_not_member").inc()
        error = _pipeline_refusal(refusal_code, setup_url)
    else:
        error = DeliveryUnavailable()
    if isinstance(error, InvalidRequest | DeliveryUnavailable):
        logger.error(
            "transactional_email_batch_recipient_rejected",
            team_id=team_id,
            status_code=status_code,
            refusal_code=refusal_code if refusal_code in PIPELINE_REFUSALS else None,
        )
    return EmailNotQueued(message_id=message_id, error=error)


def _pipeline_refusal(code: str, setup_url: Callable[[], str]) -> TransactionalEmailError:
    error_class, message = PIPELINE_REFUSALS[code]
    return error_class(message.format(setup_url=setup_url()) if "{setup_url}" in message else message)


def _schedule(answer: dict[str, Any]) -> dict[str, Any]:
    scheduled_at = answer.get("scheduled_at")
    if not isinstance(scheduled_at, str) or not scheduled_at:
        return {"status": QueuedEmailStatus.QUEUED, "scheduled_at": None}
    return {"status": QueuedEmailStatus.SCHEDULED, "scheduled_at": scheduled_at}


def _attachment_refusal(refusal_code: str | None, answer: dict[str, Any]) -> TransactionalEmailError | None:
    sha256 = answer.get("sha256") if isinstance(answer.get("sha256"), str) else None
    error: TransactionalEmailError
    if refusal_code == "field_not_accepted":
        error = FieldNotAccepted("attachments")
    elif refusal_code == "attachment_not_uploaded":
        error = AttachmentNotUploaded(sha256)
    elif refusal_code == "message_too_large":
        error = MessageTooLarge(sha256)
    elif refusal_code is not None and refusal_code in FILES_REFUSALS:
        message, why, fix = FILES_REFUSALS[refusal_code]
        error = AttachmentsRefused(
            refusal_code, message, why=_explanation(answer, "reason") or why, fix=_explanation(answer, "fix") or fix
        )
    else:
        return None
    error.attachment_bytes = _attachment_bytes(answer)
    return error


def _explanation(answer: dict[str, Any], key: str) -> str | None:
    value = answer.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _sandbox_sender_warning(
    team_id: int, ignored: tuple[str, ...], message: str = SANDBOX_SENDER_WARNING
) -> SendWarning:
    setup = sending_domain_setup(team_id)
    if setup.unverified_sender_id is None:
        agent_action = (
            "Tell the user this project can only email members of their organization until it has a verified "
            f"sending domain, and ask them to verify one at {setup.setup_url}. With the PostHog MCP tools, start "
            "with integrations-email-create for the domain they send from."
        )
    else:
        agent_action = (
            "Tell the user this project can only email members of their organization until its sending domain is "
            f"verified, and ask them to finish verifying it at {setup.setup_url}. With the PostHog MCP tools, call "
            f"integrations-email-status-retrieve for integration {setup.unverified_sender_id} to get the DNS records "
            "to publish."
        )
    if ignored:
        names = " and ".join(f"`{field}`" for field in ignored)
        ignored_note = f" PostHog ignored {names}, because the PostHog test sender only sends from its own address."
        message += ignored_note
        agent_action += ignored_note
    return SendWarning(
        code=SendWarningCode.SANDBOX_SENDER,
        message=message,
        setup_url=setup.setup_url,
        agent_action=agent_action,
    )


def _attachment_bytes(answer: dict[str, Any]) -> int | None:
    total = answer.get("attachment_bytes")
    return total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None


def _send_field_an_older_pipeline_refused(error: str | None) -> str | None:
    try:
        issues = json.loads(error or "")
    except ValueError:
        return None
    for issue in issues if isinstance(issues, list) else []:
        if not isinstance(issue, dict) or issue.get("code") != "unrecognized_keys":
            continue
        if issue.get("path") == ["send", "tracking"]:
            return "tracking"
        if issue.get("path") == ["send"]:
            keys = issue.get("keys")
            if isinstance(keys, list) and keys and isinstance(keys[0], str):
                return keys[0]
    return None


def _answer(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _refusal_code(answer: dict[str, Any]) -> str | None:
    code = answer.get("error")
    return code if isinstance(code, str) else None


def prepare_attachment_uploads(team: Team, files: Sequence[AttachmentUploadRequest]) -> list[AttachmentUploadSlot]:
    payload = {"files": [{"sha256": file.sha256, "size": file.size} for file in files]}
    try:
        response = prepare_transactional_email_attachment_uploads(team.id, payload)
    except Exception as e:
        logger.exception("transactional_email_attachment_uploads_failed", team_id=team.id)
        raise DeliveryUnavailable() from e
    if response.status_code == 200:
        return _answered_slots(team, files, response)
    answer = _answer(response)
    refusal_code = _refusal_code(answer)
    if refusal_code == "field_not_accepted":
        raise FieldNotAccepted("attachments")
    if refusal_code == "message_too_large":
        sha256 = answer.get("sha256")
        raise MessageTooLarge(sha256 if isinstance(sha256, str) else None)
    if refusal_code == "upload_quota_exceeded":
        raise UploadQuotaExceeded("This project uploaded as many file bytes as it can today.")
    if response.status_code != 503:
        logger.error(
            "transactional_email_attachment_uploads_rejected",
            team_id=team.id,
            status_code=response.status_code,
            refusal_code=refusal_code,
        )
    if refusal_code == "invalid_request":
        raise InvalidRequest("The email pipeline refused this file list.")
    raise DeliveryUnavailable()


def _answered_slots(
    team: Team, files: Sequence[AttachmentUploadRequest], response: requests.Response
) -> list[AttachmentUploadSlot]:
    try:
        slots = [_upload_slot(slot) for slot in response.json()["files"]]
    except (ValueError, KeyError, TypeError) as e:
        logger.exception("transactional_email_attachment_uploads_unreadable", team_id=team.id)
        raise DeliveryUnavailable() from e
    if [slot.sha256 for slot in slots] != [file.sha256 for file in files]:
        logger.error("transactional_email_attachment_uploads_mismatched", team_id=team.id)
        raise DeliveryUnavailable()
    return slots


def _upload_slot(slot: dict[str, Any]) -> AttachmentUploadSlot:
    if slot["status"] == "present":
        return PresentAttachment(sha256=slot["sha256"], expires_at=datetime.fromisoformat(slot["expires_at"]))
    if slot["status"] != "upload":
        raise ValueError(f"Unknown attachment upload status: {slot['status']}")
    return AttachmentUploadTarget(
        sha256=_text(slot, "sha256"),
        url=_text(slot, "url"),
        method=_text(slot, "method"),
        headers=_text_map(slot, "headers"),
        url_expires_at=datetime.fromisoformat(slot["url_expires_at"]),
    )


def _text(slot: dict[str, Any], key: str) -> str:
    value = slot[key]
    if not isinstance(value, str):
        raise TypeError(f"Attachment upload `{key}` is not a string")
    return value


def _text_map(slot: dict[str, Any], key: str) -> dict[str, str]:
    value = slot[key]
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise TypeError(f"Attachment upload `{key}` is not a map of strings")
    return value
