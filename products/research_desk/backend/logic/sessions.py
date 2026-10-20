from datetime import datetime

from django.db.models import Q

from ..facade import contracts
from ..facade.enums import SessionOrigin, SessionStatus
from ..models import ResearchSession
from .emails import email_domain, normalize_emails

MAX_SESSIONS = 500


def session_to_dto(obj: ResearchSession) -> contracts.ResearchSessionDTO:
    return contracts.ResearchSessionDTO(
        id=obj.id,
        origin=SessionOrigin(obj.origin),
        external_ref=obj.external_ref,
        title=obj.title,
        start_time=obj.start_time,
        end_time=obj.end_time,
        status=SessionStatus(obj.status),
        organizer_email=obj.organizer_email,
        internal_emails=list(obj.internal_emails),
        external_emails=list(obj.external_emails),
        meeting_url=obj.meeting_url,
        brief_posted_at=obj.brief_posted_at,
        created_at=obj.created_at,
    )


def list_sessions(
    *, start_after: datetime | None = None, start_before: datetime | None = None
) -> list[ResearchSession]:
    queryset = ResearchSession.objects.order_by("start_time")
    if start_after is not None:
        queryset = queryset.filter(start_time__gte=start_after)
    if start_before is not None:
        queryset = queryset.filter(start_time__lt=start_before)
    return list(queryset[:MAX_SESSIONS])


def upsert_session(data: contracts.UpsertResearchSessionInput) -> tuple[ResearchSession, bool]:
    external_emails = normalize_emails(data.external_emails)
    session, created = ResearchSession.objects.update_or_create(
        team_id=data.team_id,
        origin=data.origin,
        external_ref=data.external_ref,
        defaults={
            "title": data.title,
            "start_time": data.start_time,
            "end_time": data.end_time,
            "status": data.status,
            "organizer_email": data.organizer_email.strip().lower(),
            "internal_emails": normalize_emails(data.internal_emails),
            "external_emails": external_emails,
            "external_domains": sorted({email_domain(e) for e in external_emails}),
            "meeting_url": data.meeting_url,
        },
    )
    return session, created


def sessions_with_contact(*, emails: list[str], domain: str | None, since: datetime) -> list[ResearchSession]:
    match = Q()
    if emails:
        match |= Q(external_emails__overlap=emails)
    if domain:
        match |= Q(external_domains__contains=[domain])
    if not match:
        return []
    return list(
        ResearchSession.objects.filter(match, start_time__gte=since)
        .exclude(status=SessionStatus.CANCELLED)
        .order_by("-start_time")
    )
