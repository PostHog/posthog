"""
Facade for research_desk.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.utils import timezone

from posthog.models.scoping import team_scope

from ..logic import brief_posting, calendar_scout, contact_check, sessions, source_discovery, sources
from ..models import ResearchSource
from . import contracts
from .enums import SourceKind, SourceOrigin


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
    return [
        sessions.session_to_dto(obj)
        for obj in sessions.list_sessions(start_after=start_after, start_before=start_before)
    ]


def upsert_session(data: contracts.UpsertResearchSessionInput) -> tuple[contracts.ResearchSessionDTO, bool]:
    session, created = sessions.upsert_session(data)
    return sessions.session_to_dto(session), created


def post_due_briefs() -> int:
    return brief_posting.post_due_briefs()


def check_contact(data: contracts.ContactCheckInput) -> contracts.ContactCheckResult:
    return contact_check.check_contact(data)


def run_calendar_scout(team_id: int) -> contracts.CalendarScoutResult:
    with team_scope(team_id):
        counts = calendar_scout.sync_sessions_from_calendar(team_id, now=timezone.now())
    return contracts.CalendarScoutResult(
        meetings=counts.meetings, sessions_created=counts.sessions_created, sessions_updated=counts.sessions_updated
    )


def run_source_discovery(team_id: int) -> contracts.SourceDiscoveryResult:
    with team_scope(team_id):
        created = source_discovery.register_discovered_sources(team_id, now=timezone.now())
        return contracts.SourceDiscoveryResult(sources_created=[_source_to_dto(s) for s in created])
