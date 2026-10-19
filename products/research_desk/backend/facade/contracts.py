"""Contract types for research_desk."""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import SessionOrigin, SessionStatus, SourceKind, SourceOrigin, TouchChannel


class ResearchSourceNotFoundError(Exception):
    pass


class ResearchSourceAlreadyExistsError(Exception):
    pass


@dataclass(frozen=True)
class ResearchSourceDTO:
    id: UUID
    kind: SourceKind
    external_id: str
    label: str
    owner_email: str
    product_area: str
    origin: SourceOrigin
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreateResearchSourceInput:
    team_id: int
    kind: SourceKind
    external_id: str
    label: str
    owner_email: str = ""
    product_area: str = ""
    origin: SourceOrigin = SourceOrigin.MANUAL


@dataclass(frozen=True)
class UpdateResearchSourceInput:
    label: str | None = None
    owner_email: str | None = None
    product_area: str | None = None
    active: bool | None = None


@dataclass(frozen=True)
class ResearchSessionDTO:
    id: UUID
    origin: SessionOrigin
    external_ref: str
    title: str
    start_time: datetime
    end_time: datetime | None
    status: SessionStatus
    organizer_email: str
    internal_emails: list[str]
    external_emails: list[str]
    meeting_url: str
    brief_posted_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class UpsertResearchSessionInput:
    team_id: int
    origin: SessionOrigin
    external_ref: str
    start_time: datetime
    status: SessionStatus
    title: str = ""
    end_time: datetime | None = None
    organizer_email: str = ""
    internal_emails: tuple[str, ...] = ()
    external_emails: tuple[str, ...] = ()
    meeting_url: str = ""


@dataclass(frozen=True)
class ContactCheckInput:
    team_id: int
    emails: tuple[str, ...] = ()
    domain: str | None = None
    lookback_days: int = 180
    warn_within_days: int = 60


@dataclass(frozen=True)
class ResearchTouch:
    channel: TouchChannel
    contact: str
    source_label: str
    owner_email: str
    occurred_at: datetime | None
    source_id: UUID | None = None
    session_id: UUID | None = None


@dataclass(frozen=True)
class ContactCheckResult:
    emails: list[str]
    domain: str | None
    touches: list[ResearchTouch]
    last_touch_at: datetime | None
    recently_contacted: bool
    warn_within_days: int
    lookback_days: int
