"""
Facade for research_desk.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ..logic import contact_check, sessions, sources
from ..models import ResearchSession, ResearchSource
from . import contracts
from .enums import SessionOrigin, SessionStatus, SourceKind, SourceOrigin


def _source_to_dto(obj: ResearchSource) -> contracts.ResearchSourceDTO:
    return contracts.ResearchSourceDTO(
        id=obj.id,
        kind=SourceKind(obj.kind),
        external_id=obj.external_id,
        label=obj.label,
        owner_email=obj.owner_email,
        product_area=obj.product_area,
        origin=SourceOrigin(obj.origin),
        active=obj.active,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _session_to_dto(obj: ResearchSession) -> contracts.ResearchSessionDTO:
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


def list_sources(*, active_only: bool = False) -> list[contracts.ResearchSourceDTO]:
    return [_source_to_dto(obj) for obj in sources.list_sources(active_only=active_only)]


def create_source(data: contracts.CreateResearchSourceInput) -> contracts.ResearchSourceDTO:
    return _source_to_dto(sources.create_source(data))


def update_source(
    team_id: int, source_id: UUID, data: contracts.UpdateResearchSourceInput
) -> contracts.ResearchSourceDTO:
    return _source_to_dto(sources.update_source(team_id, source_id, data))


def list_sessions(
    *, start_after: datetime | None = None, start_before: datetime | None = None
) -> list[contracts.ResearchSessionDTO]:
    return [_session_to_dto(obj) for obj in sessions.list_sessions(start_after=start_after, start_before=start_before)]


def upsert_session(data: contracts.UpsertResearchSessionInput) -> tuple[contracts.ResearchSessionDTO, bool]:
    session, created = sessions.upsert_session(data)
    return _session_to_dto(session), created


def check_contact(data: contracts.ContactCheckInput) -> contracts.ContactCheckResult:
    return contact_check.check_contact(data)
