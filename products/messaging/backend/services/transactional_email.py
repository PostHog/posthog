"""Transactional emails: a template made sendable over the API. Each one is backed by a workflow that runs once
per send, so sends get the workflow's metrics, run history and versions."""

import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from email.utils import parseaddr
from typing import Any, Literal, Protocol
from uuid import UUID

from django.db import connection, transaction

import requests
import structlog
from prometheus_client import Counter, Histogram

from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import (
    send_accepted_transactional_email,
    send_transactional_email as run_transactional_workflow,
)

from products.messaging.backend.facade.contracts import (
    CodeEmail,
    ContentTooLarge,
    DeliveryUnavailable,
    IdempotencyKeyInFlight,
    IdempotencyKeyReused,
    InvalidIdempotencyKey,
    InvalidRecipient,
    InvalidRequest,
    MarketingTemplate,
    NamedSenderNotVerified,
    QueuedEmail,
    QuotaLimited,
    RecipientSuppressed,
    RecipientUnreachable,
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
)
from products.messaging.backend.models import FirstCodeSend, MessageCategory, MessageTemplate, TransactionalEmailKey
from products.messaging.backend.models.message_category import MessageCategoryType
from products.messaging.backend.services.html_text import text_from_html
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_summary
from products.workflows.backend.facade.transactional_emails import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSandboxSender,
    TransactionalEmailSenderRequired,
    TransactionalEmailSenderUnavailable,
    code_send_sender_id,
    create_code_email_workflow,
    create_transactional_email_workflow,
    resolve_transactional_email_sender,
    update_transactional_email_workflow,
)

SANDBOX_SENDER_TRANSACTIONAL_MESSAGE = (
    "The sandbox sender can't send transactional email. Choose a sender on your own verified domain."
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
}

IDEMPOTENCY_KEY_PATTERN = re.compile(r"[!-~]{1,255}")

TRANSACTIONAL_EMAIL_KEY_LIMIT = 1000
TRANSACTIONAL_EMAIL_KEY_LOCK = "transactional-email-keys"


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
        except TransactionalEmailSandboxSender as e:
            raise SenderUnavailable(SANDBOX_SENDER_TRANSACTIONAL_MESSAGE) from e
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
    except TransactionalEmailSandboxSender as e:
        raise SenderUnavailable(SANDBOX_SENDER_TRANSACTIONAL_MESSAGE) from e
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
        raise TransactionalEmailPaused("This email's workflow no longer exists.") from e
    if workflow.status != "active":
        raise TransactionalEmailPaused("This email's workflow isn't active. Turn it back on to send.")


def _code_email_workflow_id(team_id: int, key: str) -> UUID:
    template = _template_for_key(team_id, key)
    if template is not None:
        return _transactional_workflow_id(team_id, template)
    hog_flow_id = _key_workflow_id(team_id, key)
    _require_active(team_id, hog_flow_id)
    return hog_flow_id


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
        keys.create(team_id=team_id, key=key, hog_flow_id=hog_flow_id)
        return hog_flow_id


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
    with transactional_email_stage("workflow_lookup"):
        accepted_send = _accepted_send(team.id, email)
        hog_flow_id = _code_email_workflow_id(team.id, email.key)
    payload = {**_send_payload(to, distinct_id, {}, idempotency_key), "send": accepted_send}
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
    accepted: dict[str, Any] = {
        "content": _without_empty(
            {"subject": email.subject, "html": email.html, "text": email.text or text_from_html(email.html)}
        ),
        "from": _without_empty(_code_send_sender(team_id, email.sender)),
        "tracking": {"captureEngagement": email.capture_engagement},
    }
    if email.reply_to:
        accepted["replyTo"] = list(email.reply_to)
    return accepted


def _code_send_sender(team_id: int, address: str | None) -> dict[str, Any]:
    name, email = parseaddr(address) if address else ("", "")
    try:
        sender_id = code_send_sender_id(team_id=team_id, email=email or None)
    except TransactionalEmailSenderRequired as e:
        raise SenderRequired(
            "This project has more than one verified sender and no default sender. Send `from` to choose one."
        ) from e
    except TransactionalEmailSandboxSender as e:
        raise SenderUnavailable(SANDBOX_SENDER_TRANSACTIONAL_MESSAGE) from e
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

    if response.status_code == 413:
        raise ContentTooLarge(
            "The email is larger than PostHog can send. Make its content or data smaller, and link to "
            "large images and files instead of embedding them."
        )
    if response.status_code != 202:
        refusal_code = _refusal_code(response)
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
        raise error_class(message)

    body = response.json()
    return QueuedEmail(message_id=str(body["invocation_id"]), replayed=bool(body.get("replayed", False)))


def _refusal_code(response: requests.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None
