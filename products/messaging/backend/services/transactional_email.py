"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

import re
import json
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Literal, Protocol
from uuid import UUID

from django.db import connection, transaction

import requests
import structlog
import posthoganalytics
from bs4 import BeautifulSoup
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.helpers.email_utils import email_domain
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import (
    prepare_transactional_email_attachment_uploads,
    send_accepted_transactional_email,
    send_transactional_email as run_transactional_workflow,
)

from products.messaging.backend.facade.contracts import (
    AttachmentNotUploaded,
    AttachmentsRefused,
    AttachmentUploadRequest,
    AttachmentUploadSlot,
    AttachmentUploadTarget,
    CodeEmail,
    ContentTooLarge,
    CopiesNotAllowed,
    DeliveryUnavailable,
    EmailAttachment,
    FieldNotAccepted,
    IdempotencyKeyInFlight,
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    InvalidRecipient,
    InvalidRequest,
    MarketingTemplate,
    MessageCategoryKind,
    MessageTooLarge,
    NamedSenderNotVerified,
    PresentAttachment,
    QueuedEmail,
    QuotaLimited,
    RecipientOptedOut,
    RecipientSuppressed,
    RecipientUnreachable,
    SendCategory,
    SenderNotVerified,
    SenderRequired,
    SenderUnavailable,
    SendingPaused,
    SendingSuspended,
    TemplateNotSendable,
    TemplateNotTransactional,
    TooManyKeys,
    TransactionalEmailError,
    TransactionalEmailPaused,
    UnsubscribeLinkRequired,
    UploadQuotaExceeded,
)
from products.messaging.backend.models import FirstCodeSend, MessageCategory, MessageTemplate, TransactionalEmailKey
from products.messaging.backend.models.message_category import MessageCategoryType
from products.messaging.backend.services.code_email_source import source_detection_enabled
from products.messaging.backend.services.html_text import UNSUBSCRIBE_PLACEHOLDER, text_from_html
from products.messaging.backend.services.send_categories import (
    RequestedCategory,
    code_send_category,
    requested_kind,
    template_category,
    template_send_category,
)
from products.messaging.backend.tasks import detect_code_email_source_task
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary
from products.workflows.backend.facade.transactional_emails import (
    TransactionalEmailCategoryType,
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderRequired,
    TransactionalEmailSenderUnavailable,
    code_send_sender_id,
    create_code_email_workflow,
    create_transactional_email_workflow,
    get_transactional_email_message,
    resolve_transactional_email_sender,
    update_transactional_email_workflow,
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


UNSUBSCRIBE_LINK_REQUIRED = (
    "A marketing email needs an unsubscribe link that readers can click. Use `{{ unsubscribe_url }}` as a link's "
    'whole `href`, such as `<a href="{{ unsubscribe_url }}">Unsubscribe</a>`, and PostHog fills in the recipient\'s '
    "link. An email with no `html` can put it in its `text`."
)
COPIES_NOT_ALLOWED = "A marketing email can't have `cc` or `bcc` recipients. Send each recipient their own email."

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
    "recipient_opted_out": (
        RecipientOptedOut,
        "The recipient opted out of this message category or of all marketing email, so the email can't be sent.",
    ),
    "unsubscribe_link_required": (UnsubscribeLinkRequired, UNSUBSCRIBE_LINK_REQUIRED),
    "copies_not_allowed": (CopiesNotAllowed, COPIES_NOT_ALLOWED),
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
}

CODE_SEND_CATEGORIES_FLAG = "workflows-code-send-categories"
LIQUID_UNSUBSCRIBE_PLACEHOLDER = re.compile(
    r"\{\{-?\s*unsubscribe_url(_one_click)?\s*-?\}\}|\{%-?\s*unsubscribe_url\s*-?%\}", re.ASCII
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

TRANSACTIONAL_EMAIL_KEY_LIMIT = 1000
TRANSACTIONAL_EMAIL_KEY_LOCK = "transactional-email-keys"


def check_sendable(team_id: int, *, template_type: str, content: dict, message_category_id: UUID | None) -> None:
    """Raise when a template with these fields can't be sent over the API."""
    _require_email_content(template_type, content)
    if _sends_as_marketing(team_id, template_category(team_id, message_category_id)):
        _require_unsubscribe_link_in_template(content["email"])


def check_unsubscribe_link_kept(template_id: UUID, team_id: int, content: dict) -> None:
    template = MessageTemplate.objects.get(team_id=team_id, id=template_id)
    category = template_category(team_id, template.message_category_id)
    if _is_marketing(category) and code_send_categories_enabled(team_id):
        _require_unsubscribe_link_in_template((content or {}).get("email") or {})


def code_send_categories_enabled(team_id: int) -> bool:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    return bool(
        posthoganalytics.feature_enabled(
            CODE_SEND_CATEGORIES_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    )


def _require_email_content(template_type: str, content: dict) -> None:
    email = (content or {}).get("email")
    if template_type != "email" or not isinstance(email, dict) or not email.get("subject"):
        raise TemplateNotSendable("The template has no email subject, so it can't be sent.")
    if not (email.get("text") or email.get("html")):
        raise TemplateNotSendable("The template has no email body, so it can't be sent.")


def _sends_as_marketing(team_id: int, category: MessageCategory | None) -> bool:
    if not _is_marketing(category):
        return False
    if not code_send_categories_enabled(team_id):
        raise MarketingTemplate("The template is in a marketing category. Only transactional templates can be sent.")
    return True


def _is_marketing(category: MessageCategory | None) -> bool:
    return category is not None and category.category_type == MessageCategoryType.MARKETING


def _require_unsubscribe_link_in_template(email: dict[str, Any]) -> None:
    html, text = email.get("html") or "", email.get("text") or ""
    if html:
        has_link = bool(BeautifulSoup(html, "html.parser").find_all("a", href=LIQUID_UNSUBSCRIBE_PLACEHOLDER))
    else:
        has_link = bool(LIQUID_UNSUBSCRIBE_PLACEHOLDER.search(text))
    if not has_link:
        raise UnsubscribeLinkRequired(UNSUBSCRIBE_LINK_REQUIRED)


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
        message_category_type=_step_category_type(template),
        sensitive=template.sensitive,
        from_email=sender.get("email") or "",
        from_name=sender.get("name") or "",
        reply_to=email.get("replyTo") or "",
    )


def _step_category_type(template: MessageTemplate) -> TransactionalEmailCategoryType:
    category = template_category(template.team_id, template.message_category_id)
    if _is_marketing(category) and code_send_categories_enabled(template.team_id):
        return "marketing"
    return "transactional"


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
    except WorkflowNotFound:
        # Deleted between the check above and the update.
        MessageTemplate.objects.filter(team_id=team_id, id=template_id).update(transactional_hog_flow_id=None)
    except TransactionalEmailContentInvalid as e:
        raise TemplateNotSendable("The template needs a subject and a body to send.") from e
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


@frozen
class TemplateSend:
    hog_flow_id: UUID
    category: MessageCategory | None
    marketing: bool


def _template_send(team_id: int, template: TransactionalTemplate | MessageTemplate) -> TemplateSend:
    if not template.transactional_hog_flow_id:
        raise TemplateNotTransactional("The template isn't transactional. Make it transactional to send it.")
    _require_email_content(template.type, template.content)
    category = template_category(team_id, template.message_category_id)
    marketing = _sends_as_marketing(team_id, category)
    _require_active(team_id, template.transactional_hog_flow_id)
    return TemplateSend(hog_flow_id=template.transactional_hog_flow_id, category=category, marketing=marketing)


def _require_active(team_id: int, hog_flow_id: UUID) -> None:
    try:
        workflow = get_workflow_summary(team_id=team_id, workflow_id=str(hog_flow_id))
    except WorkflowNotFound as e:
        raise TransactionalEmailPaused("This email's workflow no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalEmailPaused("This email's workflow isn't active. Turn it back on to send.")


def _template_for_key(team_id: int, key: str) -> MessageTemplate | None:
    return MessageTemplate.objects.filter(team_id=team_id, key=key, deleted=False).first()


def known_key(team_id: int, key: str) -> TransactionalEmailKey | None:
    return TransactionalEmailKey.objects.for_team(team_id, canonical=True).filter(key=key).first()


def _key_workflow_id(team_id: int, key: str) -> UUID:
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


def _lock_team_keys(team_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"{TRANSACTIONAL_EMAIL_KEY_LOCK}:{team_id}"]
        )


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
    category: RequestedCategory = None,
    timeout: float = 10,
) -> QueuedEmail:
    _check_send_request(to, idempotency_key)
    with transactional_email_stage("workflow_lookup"):
        # A template passed in must be one of the team's templates that is not deleted, as this lookup returns.
        loaded = (
            MessageTemplate.objects.get(team_id=team.id, id=template, deleted=False)
            if isinstance(template, UUID)
            else template
        )
        send = _template_send(team.id, loaded)
        send_category = _send_category(team.id, send, category)
        if send.marketing:
            _require_marketing_template_step(team.id, send.hog_flow_id)
    payload = _send_payload(to, distinct_id, message_data, idempotency_key)
    if send_category is not None:
        payload["message_category"] = {"id": str(send_category.id), "type": send_category.type}
    queued = _queue(team.id, send.hog_flow_id, payload, run_transactional_workflow, timeout=timeout)
    return replace(queued, category_type=_kind_of(send_category))


def send_code_email(
    team: Team,
    email: CodeEmail,
    *,
    to: str,
    distinct_id: str | None,
    idempotency_key: str | None = None,
) -> QueuedEmail:
    _check_send_request(to, idempotency_key, (*email.cc, *email.bcc))
    with transactional_email_stage("workflow_lookup"):
        template = _template_for_key(team.id, email.key)
        category: SendCategory | None = None
        if template is not None:
            send = _template_send(team.id, template)
            hog_flow_id = send.hog_flow_id
            category = _send_category(team.id, send, email.category)
            kind = _kind_of(category)
        else:
            kind = requested_kind(email.category)
        _require_marketing_rules(email, kind)
        accepted_send = _accepted_send(team.id, email, kind)
        if template is None:
            with transaction.atomic():
                hog_flow_id = _key_workflow_id(team.id, email.key)
                _require_active(team.id, hog_flow_id)
                category = code_send_category(team.id, email.category)
    payload = {**_send_payload(to, distinct_id, {}, idempotency_key), "send": accepted_send}
    if category is not None:
        payload["message_category"] = {"id": str(category.id), "type": category.type}
    queued = _queue(team.id, hog_flow_id, payload, send_accepted_transactional_email)
    return replace(queued, category_type=_kind_of(category))


def _check_send_request(to: str, idempotency_key: str | None, copies: tuple[str, ...] = ()) -> None:
    if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise InvalidIdempotencyKey(
            "The Idempotency-Key header must be 1 to 255 visible ASCII characters, with no spaces."
        )
    # Defense in depth: the workflow reads the recipient from an event property, which Liquid outputs as typed.
    if "{" in to or "}" in to:
        raise InvalidRecipient("The recipient address can't contain { or }.")
    if any("{" in address or "}" in address for address in copies):
        raise InvalidRecipient("A `cc` or `bcc` address can't contain { or }.")


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


def _send_category(team_id: int, send: TemplateSend, requested: RequestedCategory) -> SendCategory | None:
    category = template_send_category(send.category, requested)
    if send.marketing or category is None or code_send_categories_enabled(team_id):
        return category
    return None


def _kind_of(category: SendCategory | None) -> MessageCategoryKind:
    return "transactional" if category is None else category.type


def _require_marketing_template_step(team_id: int, hog_flow_id: UUID) -> None:
    message = get_transactional_email_message(team_id=team_id, hog_flow_id=hog_flow_id)
    if not LIQUID_UNSUBSCRIBE_PLACEHOLDER.search(message.html or message.text):
        raise UnsubscribeLinkRequired(UNSUBSCRIBE_LINK_REQUIRED)
    if message.has_copies:
        raise CopiesNotAllowed(COPIES_NOT_ALLOWED)


def _require_marketing_rules(email: CodeEmail, kind: MessageCategoryKind) -> None:
    if kind != "marketing":
        return
    if not UNSUBSCRIBE_PLACEHOLDER.search(email.html or email.text):
        raise UnsubscribeLinkRequired(UNSUBSCRIBE_LINK_REQUIRED)
    if email.cc or email.bcc:
        raise CopiesNotAllowed(COPIES_NOT_ALLOWED)


def _accepted_send(team_id: int, email: CodeEmail, kind: MessageCategoryKind) -> dict[str, Any]:
    accepted: dict[str, Any] = {
        "content": _without_empty(
            {
                "subject": email.subject,
                "html": email.html,
                "text": email.text or text_from_html(email.html, keep_unsubscribe_link=kind == "marketing"),
            }
        ),
        "from": _without_empty(_code_send_sender(team_id, email.sender)),
        "tracking": {"captureEngagement": email.capture_engagement},
    }
    if email.reply_to:
        accepted["replyTo"] = list(email.reply_to)
    if email.cc:
        accepted["cc"] = list(email.cc)
    if email.bcc:
        accepted["bcc"] = list(email.bcc)
    if email.attachments:
        accepted["attachments"] = [_accepted_attachment(attachment) for attachment in email.attachments]
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


def _code_send_sender(team_id: int, address: str | None) -> dict[str, Any]:
    name, email = parseaddr(address) if address else ("", "")
    try:
        sender_id = code_send_sender_id(team_id=team_id, email=email or None)
    except TransactionalEmailSenderRequired as e:
        raise SenderRequired(
            "This project has more than one verified sender and no default sender. Send `from` to choose one."
        ) from e
    except TransactionalEmailSenderUnavailable as e:
        if address:
            raise NamedSenderNotVerified(f"No verified sender in this project can send from `{email}`.") from e
        raise SenderNotVerified("This project has no verified email sender. Verify a sender domain first.") from e
    return {"integrationId": sender_id, "email": email, "name": name}


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
        error = error_class(message)
        error.attachment_bytes = _attachment_bytes(answer)
        raise error

    return QueuedEmail(
        message_id=str(answer["invocation_id"]),
        replayed=bool(answer.get("replayed", False)),
        attachment_bytes=_attachment_bytes(answer),
    )


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


def _attachment_bytes(answer: dict[str, Any]) -> int | None:
    total = answer.get("attachment_bytes")
    return total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None


def _send_field_an_older_pipeline_refused(error: str | None) -> str | None:
    try:
        issues = json.loads(error or "")
    except ValueError:
        return None
    for issue in issues if isinstance(issues, list) else []:
        if isinstance(issue, dict) and issue.get("code") == "unrecognized_keys" and issue.get("path") == ["send"]:
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
