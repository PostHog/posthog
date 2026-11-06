"""From an SES notification to stored mail and an event, for each team a message names.

The verdicts come only from the SNS-signed notification. A sender can write any header into the message, including a
fake `Authentication-Results`, so nothing about trust is read from the MIME.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
from prometheus_client import Counter

from posthog.api.capture import capture_internal
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.redis import get_client
from posthog.storage import object_storage

from products.workflows.backend.facade.enums import (
    InboundEmailContentStatus as ContentStatus,
    InboundEmailDomainStatus as DomainStatus,
    ReceivedEmailFilterReason as FilterReason,
    ReceivedEmailStatus as Status,
)
from products.workflows.backend.models import InboundEmailDomain, ReceivedEmail
from products.workflows.backend.services.inbound_email import storage
from products.workflows.backend.services.inbound_email.domains import check_domain_mx, domains_for_recipients
from products.workflows.backend.services.inbound_email.matching import find_original_send, find_person_by_email
from products.workflows.backend.services.inbound_email.parsing import (
    MAX_ADDRESS_CHARS,
    MAX_MESSAGE_ID_CHARS,
    MAX_RAW_BYTES,
    MAX_SUBJECT_CHARS,
    ParsedEmail,
    is_system_sender,
    parse_email,
    scrub_recipient_trace_headers,
)

logger = structlog.get_logger(__name__)

INBOUND_EMAIL_OUTCOMES = Counter(
    "workflows_inbound_email_outcomes_total",
    "What happened to each message or team copy that reached inbound email intake.",
    labelnames=["outcome"],
)

EMAIL_RECEIVED_EVENT = "$email_received"
EVENT_SOURCE = "workflows_inbound_email"
RECEIVED_EMAIL_NAMESPACE = uuid.UUID("9b6a4f31-7f5c-4a2e-8d10-3c1e5f7a9b24")
TEAM_DAILY_LIMIT = 10_000
SENDER_HOURLY_LIMIT = 60
FAIL = "FAIL"
PASS = "PASS"
GRAY = "GRAY"


class IntakeObjectMissing(Exception):
    pass


class MxLookupUnavailable(Exception):
    pass


@frozen
class InboundNotification:
    ses_message_id: str
    bucket: str
    object_key: str
    recipients: tuple[str, ...]
    envelope_from: str
    timestamp: datetime
    spf: str
    dkim: str
    dmarc: str
    spam: str
    virus: str
    common_headers: Mapping[str, Any]


@frozen
class _Route:
    domain: InboundEmailDomain
    recipients: tuple[str, ...]


def parse_notification(payload: Mapping[str, Any]) -> InboundNotification | None:
    """None for anything but a notification of a message stored in object storage."""
    mail = payload.get("mail")
    receipt = payload.get("receipt")
    if (
        payload.get("notificationType") != "Received"
        or not isinstance(mail, Mapping)
        or not isinstance(receipt, Mapping)
    ):
        return None
    action = receipt.get("action")
    if not isinstance(action, Mapping) or action.get("type") != "S3":
        return None
    ses_message_id = mail.get("messageId")
    object_key = action.get("objectKey")
    recipients = receipt.get("recipients")
    if not (isinstance(ses_message_id, str) and ses_message_id and isinstance(object_key, str) and object_key):
        return None
    if not isinstance(recipients, list):
        return None
    common_headers = mail.get("commonHeaders")
    return InboundNotification(
        ses_message_id=ses_message_id[:128],
        bucket=str(action.get("bucketName", "")),
        object_key=object_key,
        recipients=tuple(sorted({str(recipient).strip().lower() for recipient in recipients if recipient})),
        envelope_from=str(mail.get("source", "") or "").strip()[:MAX_ADDRESS_CHARS],
        timestamp=_parse_timestamp(receipt.get("timestamp") or mail.get("timestamp")),
        spf=_verdict(receipt, "spfVerdict"),
        dkim=_verdict(receipt, "dkimVerdict"),
        dmarc=_verdict(receipt, "dmarcVerdict"),
        spam=_verdict(receipt, "spamVerdict"),
        virus=_verdict(receipt, "virusVerdict"),
        common_headers=common_headers if isinstance(common_headers, Mapping) else {},
    )


def process_notification(payload: Mapping[str, Any]) -> None:
    notification = parse_notification(payload)
    if notification is None:
        INBOUND_EMAIL_OUTCOMES.labels(outcome="ignored_notification").inc()
        return
    intake_prefix = settings.WORKFLOWS_INBOUND_EMAIL_INTAKE_PREFIX
    if notification.bucket != storage.bucket() or not notification.object_key.startswith(intake_prefix):
        # A signed notification naming another location means the receipt rule is misconfigured.
        logger.error("inbound_email_unexpected_location", ses_message_id=notification.ses_message_id)
        INBOUND_EMAIL_OUTCOMES.labels(outcome="unexpected_location").inc()
        return
    if notification.virus == FAIL:
        _discard(notification, "virus")
        return
    routes = _routes(notification)
    if not routes:
        _discard(notification, "unknown_domain")
        return

    failures: list[Exception] = []
    new_routes: list[_Route] = []
    for route in routes:
        try:
            if _needs_delivery(notification, route):
                new_routes.append(route)
        except Exception as error:
            failures.append(_logged_failure(notification, route, error))

    if new_routes:
        # A team over its limit, or a redelivery, must not cost a download of up to 40 MB.
        size = _object_size(notification)
        if size is None:
            raise IntakeObjectMissing(notification.ses_message_id)
        raw = (
            None
            if size > MAX_RAW_BYTES
            else object_storage.read_bytes(notification.object_key, bucket=storage.bucket())
        )
        for route in new_routes:
            try:
                _deliver_to_team(notification, route, raw, size)
            except Exception as error:
                # One team's failure must not cost the other team its mail; the retry skips what was delivered.
                failures.append(_logged_failure(notification, route, error))
    if failures:
        raise failures[0]
    object_storage.delete(notification.object_key, bucket=storage.bucket())


def received_email_id(team_id: int, ses_message_id: str) -> uuid.UUID:
    return uuid.uuid5(RECEIVED_EMAIL_NAMESPACE, f"{team_id}:{ses_message_id}")


def is_sender_verified(*, dmarc: str, spf: str, envelope_from: str, from_address: str) -> bool:
    """DMARC proves the From domain. With no DMARC policy, SPF counts only when it covers that same domain.

    SES's DKIM verdict doesn't say which domain signed, so it can't vouch for the From on its own.
    """
    if not from_address:
        return False
    if dmarc == PASS:
        return True
    if dmarc in (FAIL, "PROCESSING_FAILED"):
        return False
    return spf == PASS and _domain_of(envelope_from) == _domain_of(from_address)


def _needs_delivery(notification: InboundNotification, route: _Route) -> bool:
    """False when this team already has the mail, or is over its limit and drops it."""
    team_id = route.domain.team_id
    email_id = received_email_id(team_id, notification.ses_message_id)
    existing = ReceivedEmail.objects.for_team(team_id).filter(pk=email_id).first()
    if existing is not None:
        _capture_if_owed(existing)
        return False
    if _over_daily_limit(team_id):
        InboundEmailDomain.objects.for_team(team_id).filter(pk=route.domain.pk).update(
            daily_limit_reached_at=timezone.now()
        )
        INBOUND_EMAIL_OUTCOMES.labels(outcome="team_daily_limit").inc()
        return False
    return True


def _logged_failure(notification: InboundNotification, route: _Route, error: Exception) -> Exception:
    logger.error(
        "inbound_email_delivery_failed",
        team_id=route.domain.team_id,
        ses_message_id=notification.ses_message_id,
        exc_info=error,
    )
    return error


def _deliver_to_team(notification: InboundNotification, route: _Route, raw: bytes | None, size: int) -> None:
    team_id = route.domain.team_id
    email_id = received_email_id(team_id, notification.ses_message_id)
    named_elsewhere = set(notification.recipients) - set(route.recipients)
    team_raw = scrub_recipient_trace_headers(raw) if raw is not None and named_elsewhere else raw
    parsed, content_status = _parse(team_raw)
    if team_raw is not None:
        storage.write_message(team_id, email_id, team_raw, parsed)

    fields = _row_fields(notification, route, parsed)
    if verified_sender := fields["sender_verified"] and fields["from_address"]:
        person = find_person_by_email(team_id, verified_sender)
        if person is not None:
            fields["person_id"], fields["person_distinct_id"] = person.person_id, person.distinct_id
    if parsed is not None:
        send = find_original_send(team_id, in_reply_to=parsed.in_reply_to, references=parsed.references)
        if send is not None:
            fields["original_message_id"] = send.message_id
            fields["original_workflow_id"] = send.workflow_id
            fields["match_method"] = send.method
    filter_reason = _filter_reason(notification, parsed, fields["from_address"], team_id)
    try:
        with transaction.atomic():
            email, created = ReceivedEmail.objects.for_team(team_id).get_or_create(
                id=email_id,
                team_id=team_id,
                defaults={
                    **fields,
                    "domain": route.domain,
                    "ses_message_id": notification.ses_message_id,
                    "status": Status.FILTERED if filter_reason else Status.RECEIVED,
                    "filter_reason": filter_reason or "",
                    "content_status": content_status,
                    "size_bytes": size,
                    "attachment_count": len(parsed.attachments) if parsed else 0,
                    "received_at": notification.timestamp,
                },
            )
    except IntegrityError:
        email = ReceivedEmail.objects.for_team(team_id).get(pk=email_id)
    INBOUND_EMAIL_OUTCOMES.labels(outcome=f"filtered_{filter_reason}" if filter_reason else "received").inc()
    _capture_if_owed(email)


def _capture_if_owed(email: ReceivedEmail) -> None:
    if email.status != Status.RECEIVED or email.event_captured_at is not None:
        return
    token = Team.objects.only("api_token").get(pk=email.team_id).api_token
    # No person is ever created here, so strangers can't grow a team's person count. Only a sender who proved their
    # domain can land on a person, so a forged From can't attach an event to someone else.
    distinct_id = email.person_distinct_id or (
        email.from_address if email.sender_verified and email.from_address else f"received-email-{email.id}"
    )
    result = capture_internal(
        token=token,
        event_name=EMAIL_RECEIVED_EVENT,
        event_source=EVENT_SOURCE,
        distinct_id=distinct_id,
        timestamp=email.received_at,
        event_uuid=str(email.id),
        process_person_profile=False,
        properties=_event_properties(email),
    )
    result.raise_for_status()
    ReceivedEmail.objects.for_team(email.team_id).filter(pk=email.pk).update(event_captured_at=timezone.now())


def _event_properties(email: ReceivedEmail) -> dict[str, Any]:
    """Metadata only. Body text never enters the event stream, where it would be hard to delete."""
    recipients = list(email.envelope_recipients)
    return {
        "$email_received_id": str(email.id),
        "$email_from": email.from_address,
        "$email_from_name": email.from_name,
        "$email_envelope_from": email.envelope_from,
        "$email_recipient": recipients[0] if recipients else "",
        "$email_recipients": recipients,
        "$email_to_addresses": email.to_addresses,
        "$email_cc_addresses": email.cc_addresses,
        "$email_subject": email.subject,
        # Named like the send events' property, so a delivery webhook reads one ID the API accepts on either kind.
        "$email_message_id": str(email.id),
        "$email_internet_message_id": email.message_id,
        "$email_in_reply_to": email.in_reply_to,
        "$email_is_reply": bool(email.in_reply_to),
        "$email_spf": email.spf_verdict.lower(),
        "$email_dkim": email.dkim_verdict.lower(),
        "$email_dmarc": email.dmarc_verdict.lower(),
        "$email_spam_verdict": email.spam_verdict.lower(),
        "$email_virus_verdict": email.virus_verdict.lower(),
        "$email_sender_verified": email.sender_verified,
        "$email_attachment_count": email.attachment_count,
        "$email_size_bytes": email.size_bytes,
        "$email_original_message_id": str(email.original_message_id) if email.original_message_id else "",
        "$email_original_workflow_id": str(email.original_workflow_id) if email.original_workflow_id else "",
        "$email_match_method": email.match_method or "none",
        "$email_body_included": False,
        "$email_content_url": f"/api/projects/{email.team_id}/received_emails/{email.id}/",
    }


def _routes(notification: InboundNotification) -> list[_Route]:
    candidates = domains_for_recipients(notification.recipients)
    # Several teams may hold a pending row for one name, so an active row always wins it.
    active: dict[str, InboundEmailDomain] = {d.domain: d for d in candidates if d.status == DomainStatus.ACTIVE}
    for domain in candidates:
        if domain.domain not in active and domain.status == DomainStatus.PENDING:
            # Arriving mail doesn't prove the MX, since anyone can name a domain at the SES endpoint, so check it.
            # This also means a customer who added the record and left doesn't lose their first mail.
            state = check_domain_mx(domain).state
            if state == "lookup_failed":
                # This may be the domain's mail, so it stays in intake until DNS can answer.
                raise MxLookupUnavailable(domain.domain)
            if state == "active":
                active[domain.domain] = domain

    recipients_by_team: dict[int, list[str]] = {}
    domain_by_team: dict[int, InboundEmailDomain] = {}
    for recipient in notification.recipients:
        route_domain = active.get(recipient.rpartition("@")[2])
        if route_domain is not None:
            recipients_by_team.setdefault(route_domain.team_id, []).append(recipient)
            domain_by_team.setdefault(route_domain.team_id, route_domain)
    return [
        _Route(domain=domain_by_team[team_id], recipients=tuple(recipients))
        for team_id, recipients in recipients_by_team.items()
    ]


def _discard(notification: InboundNotification, outcome: str) -> None:
    object_storage.delete(notification.object_key, bucket=storage.bucket())
    INBOUND_EMAIL_OUTCOMES.labels(outcome=outcome).inc()


def _object_size(notification: InboundNotification) -> int | None:
    head = object_storage.head_object(notification.object_key, bucket=storage.bucket())
    return None if head is None else int(head.get("ContentLength", 0))


def _parse(raw: bytes | None) -> tuple[ParsedEmail | None, str]:
    if raw is None:
        return None, ContentStatus.TOO_LARGE
    try:
        return parse_email(raw), ContentStatus.AVAILABLE
    except Exception:
        # The raw message is still kept and offered for download, so nothing is lost to a parser bug.
        logger.warning("inbound_email_parse_failed", exc_info=True)
        INBOUND_EMAIL_OUTCOMES.labels(outcome="parse_failed").inc()
        return None, ContentStatus.PARSE_FAILED


def _row_fields(notification: InboundNotification, route: _Route, parsed: ParsedEmail | None) -> dict[str, Any]:
    if parsed is not None:
        identity: dict[str, Any] = {
            "from_address": parsed.from_address,
            "from_name": parsed.from_name,
            "subject": parsed.subject,
            "message_id": parsed.message_id,
            "in_reply_to": parsed.in_reply_to,
            "to_addresses": list(parsed.to_addresses),
            "cc_addresses": list(parsed.cc_addresses),
            "reply_to_addresses": list(parsed.reply_to_addresses),
            "auto_submitted": parsed.auto_submitted,
        }
    else:
        identity = _identity_from_common_headers(notification.common_headers)
    from_address = identity["from_address"]
    return {
        **identity,
        "envelope_from": notification.envelope_from,
        "envelope_recipients": list(route.recipients),
        "spf_verdict": notification.spf,
        "dkim_verdict": notification.dkim,
        "dmarc_verdict": notification.dmarc,
        "spam_verdict": notification.spam,
        "virus_verdict": notification.virus,
        "sender_verified": is_sender_verified(
            dmarc=notification.dmarc,
            spf=notification.spf,
            envelope_from=notification.envelope_from,
            from_address=from_address,
        ),
    }


def _identity_from_common_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """A message we can't parse still gets a list row, from the headers SES already read."""
    from email.utils import getaddresses  # noqa: PLC0415 - only this rare path needs it

    def addresses(key: str) -> list[str]:
        values = headers.get(key)
        strings = [str(value) for value in values] if isinstance(values, list) else []
        return [address.lower()[:MAX_ADDRESS_CHARS] for _, address in getaddresses(strings) if address]

    from_values = headers.get("from")
    senders = getaddresses([str(value) for value in from_values]) if isinstance(from_values, list) else []
    name, address = senders[0] if senders else ("", "")
    return {
        "from_address": address.lower()[:MAX_ADDRESS_CHARS],
        "from_name": name[:MAX_ADDRESS_CHARS],
        "subject": str(headers.get("subject", "") or "").replace("\x00", "")[:MAX_SUBJECT_CHARS],
        "message_id": str(headers.get("messageId", "") or "").replace("\x00", "")[:MAX_MESSAGE_ID_CHARS],
        "in_reply_to": "",
        "to_addresses": addresses("to"),
        "cc_addresses": addresses("cc"),
        "reply_to_addresses": addresses("replyTo"),
        "auto_submitted": False,
    }


def _filter_reason(
    notification: InboundNotification, parsed: ParsedEmail | None, from_address: str, team_id: int
) -> str | None:
    if notification.spam == FAIL:
        return FilterReason.SPAM
    if (parsed is not None and parsed.auto_submitted) or is_system_sender(notification.envelope_from):
        return FilterReason.AUTO_REPLY
    if _over_sender_limit(team_id, from_address or notification.envelope_from):
        return FilterReason.RATE_LIMITED
    return None


def _over_daily_limit(team_id: int) -> bool:
    day = timezone.now().strftime("%Y%m%d")
    return _count_in_window(f"workflows:inbound_email:team:{team_id}:{day}", timedelta(days=2)) > TEAM_DAILY_LIMIT


def _over_sender_limit(team_id: int, sender: str) -> bool:
    """Stops a loop where an automated sender answers mail a workflow sends in answer to it. The mail is still kept."""
    hour = timezone.now().strftime("%Y%m%d%H")
    key = f"workflows:inbound_email:sender:{team_id}:{uuid.uuid5(RECEIVED_EMAIL_NAMESPACE, sender.lower())}:{hour}"
    return _count_in_window(key, timedelta(hours=2)) > SENDER_HOURLY_LIMIT


def _count_in_window(key: str, ttl: timedelta) -> int:
    client = get_client()
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, int(ttl.total_seconds()))
    return count


def _verdict(receipt: Mapping[str, Any], key: str) -> str:
    verdict = receipt.get(key)
    return str(verdict.get("status", ""))[:32] if isinstance(verdict, Mapping) else ""


def _parse_timestamp(value: Any) -> datetime:
    parsed = parse_datetime(value) if isinstance(value, str) else None
    return parsed if parsed is not None and parsed.tzinfo is not None else datetime.now(UTC)


def _domain_of(address: str) -> str:
    return address.strip().strip("<>").rpartition("@")[2].lower()
