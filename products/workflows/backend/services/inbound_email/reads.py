"""Reads and writes behind the received email API, as facade contracts."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

from products.workflows.backend.facade.contracts import (
    DomainPreflightResult,
    InboundDomain,
    InboundDomainCheck,
    InboundDomainsOverview,
    ReceivedEmailAttachment,
    ReceivedEmailDetail,
    ReceivedEmailPage,
    ReceivedEmailSummary,
)
from products.workflows.backend.facade.enums import (
    InboundEmailContentStatus,
    InboundEmailDomainKind,
    InboundEmailDomainStatus,
    ReceivedEmailStatus,
)
from products.workflows.backend.models import InboundEmailDomain, ReceivedEmail
from products.workflows.backend.services.inbound_email import (
    domains as domain_service,
    storage,
)
from products.workflows.backend.services.inbound_email.retention import RETENTION_DAYS, retention_cutoff

MX_PRIORITY = 10


def list_received_emails(
    team_id: int,
    *,
    search: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ReceivedEmailPage:
    window = _in_retention(team_id).filter(received_at__gte=date_from or timezone.now() - timedelta(days=7))
    if date_to is not None:
        window = window.filter(received_at__lt=date_to)
    if search:
        window = window.filter(
            Q(from_address__icontains=search)
            | Q(from_name__icontains=search)
            | Q(subject__icontains=search)
            | Q(message_id=search)
            | Q(envelope_recipients__icontains=search)
        )
    rows = window.filter(status=status) if status else window
    page = list(rows.order_by("-received_at", "-id")[offset : offset + limit + 1])
    # The view says when filtered mail sits behind the default filter, such as a forwarding confirmation code.
    filtered_count = window.filter(status=ReceivedEmailStatus.FILTERED).count() if status else 0
    return ReceivedEmailPage(
        results=tuple(_summary(email) for email in page[:limit]),
        has_more=len(page) > limit,
        filtered_count=filtered_count,
        has_any_email=bool(page) or _in_retention(team_id).exists(),
    )


def get_received_email(team_id: int, email_id: UUID) -> ReceivedEmailDetail | None:
    email = _in_retention(team_id).filter(pk=email_id).first()
    if email is None:
        return None
    content: dict[str, Any] = {}
    if email.content_status == InboundEmailContentStatus.AVAILABLE:
        content = storage.read_content(team_id, email_id) or {}
    expires_at = _link_expiry()
    has_raw = email.content_status != InboundEmailContentStatus.TOO_LARGE
    return ReceivedEmailDetail(
        summary=_summary(email),
        envelope_from=email.envelope_from,
        reply_to=tuple(email.reply_to_addresses),
        in_reply_to=email.in_reply_to,
        spf=email.spf_verdict.lower(),
        dkim=email.dkim_verdict.lower(),
        dmarc=email.dmarc_verdict.lower(),
        virus=email.virus_verdict.lower(),
        text=content.get("text", ""),
        html=content.get("html", ""),
        reply_text=content.get("reply_text", ""),
        body_truncated=bool(content.get("body_truncated")),
        headers=tuple((header["name"], header["value"]) for header in content.get("headers", [])),
        attachments=tuple(
            _attachment(team_id, email_id, attachment, expires_at) for attachment in content.get("attachments", [])
        ),
        attachments_dropped=int(content.get("attachments_dropped") or 0),
        raw_download_url=(
            storage.download_link(storage.raw_key(team_id, email_id), f"{email_id}.eml") if has_raw else None
        ),
        raw_expires_at=expires_at,
    )


def get_received_email_attachment(team_id: int, email_id: UUID, attachment_id: int) -> ReceivedEmailAttachment | None:
    if not _in_retention(team_id).filter(pk=email_id).exists():
        return None
    content = storage.read_content(team_id, email_id) or {}
    for attachment in content.get("attachments", []):
        if attachment["index"] == attachment_id:
            return _attachment(team_id, email_id, attachment, _link_expiry())
    return None


def get_inbound_domain_overview(team_id: int) -> InboundDomainsOverview:
    rows = InboundEmailDomain.objects.for_team(team_id).order_by("-kind", "created_at")
    return InboundDomainsOverview(
        domains=tuple(_domain(row) for row in rows),
        generated_addresses_available=domain_service.generated_addresses_available(),
        verified_sending_domains=tuple(domain_service.verified_sending_domains(team_id)),
        mx_host=domain_service.expected_mx_host(),
        mx_priority=MX_PRIORITY,
        default_subdomain=domain_service.DEFAULT_SUBDOMAIN,
        retention_days=RETENTION_DAYS,
    )


def use_receiving_address(team_id: int, *, rotate: bool, created_by_id: int | None) -> InboundDomain:
    if rotate:
        return _domain(domain_service.rotate_generated_domain(team_id, created_by_id=created_by_id))
    return _domain(domain_service.ensure_generated_domain(team_id, created_by_id=created_by_id))


def preflight_inbound_domain(team_id: int, value: str) -> DomainPreflightResult:
    preflight = domain_service.preflight_domain(team_id, value)
    return DomainPreflightResult(
        domain=preflight.domain,
        eligible=preflight.eligible,
        reason=preflight.reason,
        verified_parent=preflight.verified_parent,
        whole_domain=preflight.whole_domain,
        existing_mx=preflight.existing_mx,
        points_here=preflight.points_here,
        dns_answered=preflight.dns_answered,
    )


def create_inbound_domain(
    team_id: int, value: str, *, confirm_move_mail: bool, created_by_id: int | None
) -> InboundDomainCheck:
    row = domain_service.create_custom_domain(
        team_id, value, confirm_move_mail=confirm_move_mail, created_by_id=created_by_id
    )
    return _check(row)


def check_inbound_domain(team_id: int, domain_id: UUID) -> InboundDomainCheck | None:
    row = InboundEmailDomain.objects.for_team(team_id).filter(pk=domain_id).first()
    return _check(row) if row else None


def delete_inbound_domain(team_id: int, domain_id: UUID) -> bool:
    """Mail to the domain stops being accepted. Mail already received stays until it expires."""
    deleted, _ = (
        InboundEmailDomain.objects.for_team(team_id).filter(pk=domain_id, kind=InboundEmailDomainKind.CUSTOM).delete()
    )
    return deleted > 0


def _check(row: InboundEmailDomain) -> InboundDomainCheck:
    check = domain_service.check_domain_mx(row)
    return InboundDomainCheck(domain=_domain(check.domain), state=check.state, found=check.found)


def _in_retention(team_id: int) -> QuerySet[ReceivedEmail]:
    return ReceivedEmail.objects.for_team(team_id).filter(received_at__gte=retention_cutoff())


def _link_expiry() -> datetime:
    return timezone.now() + timedelta(seconds=storage.LINK_EXPIRY_SECONDS)


def _attachment(
    team_id: int, email_id: UUID, attachment: dict[str, Any], expires_at: datetime
) -> ReceivedEmailAttachment:
    return ReceivedEmailAttachment(
        id=attachment["index"],
        filename=attachment["filename"],
        content_type=attachment["content_type"],
        size=attachment["size"],
        content_id=attachment.get("content_id", ""),
        inline=bool(attachment.get("inline")),
        download_url=storage.download_link(
            storage.attachment_key(team_id, email_id, attachment["index"]), attachment["filename"]
        ),
        expires_at=expires_at,
    )


def _summary(email: ReceivedEmail) -> ReceivedEmailSummary:
    return ReceivedEmailSummary(
        id=email.id,
        from_address=email.from_address,
        from_name=email.from_name,
        subject=email.subject,
        to=tuple(email.to_addresses),
        cc=tuple(email.cc_addresses),
        envelope_recipients=tuple(email.envelope_recipients),
        message_id=email.message_id,
        received_at=email.received_at,
        status=ReceivedEmailStatus(email.status),
        filter_reason=email.filter_reason,
        content_status=InboundEmailContentStatus(email.content_status),
        sender_verified=email.sender_verified,
        auto_submitted=email.auto_submitted,
        attachment_count=email.attachment_count,
        size_bytes=email.size_bytes,
        spam=email.spam_verdict.lower(),
        person_id=email.person_id,
        person_distinct_id=email.person_distinct_id,
        original_message_id=email.original_message_id,
        original_workflow_id=email.original_workflow_id,
        match_method=email.match_method,
    )


def _domain(row: InboundEmailDomain) -> InboundDomain:
    return InboundDomain(
        id=row.id,
        domain=row.domain,
        kind=InboundEmailDomainKind(row.kind),
        status=InboundEmailDomainStatus(row.status),
        mx_checked_at=row.mx_checked_at,
        activated_at=row.activated_at,
        daily_limit_reached_at=row.daily_limit_reached_at,
        created_at=row.created_at,
    )
