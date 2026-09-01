"""
Contract types for docs.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import CollabSubmitStatus, DocStatus


@dataclass(frozen=True)
class PersonDTO:
    id: int
    uuid: UUID
    first_name: str
    last_name: str
    email: str


@dataclass(frozen=True)
class DocSummaryDTO:
    id: UUID
    channel_id: UUID
    title: str
    status: DocStatus
    position: int
    version: int
    created_by: PersonDTO | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocDTO:
    id: UUID
    channel_id: UUID
    title: str
    status: DocStatus
    position: int
    version: int
    content: dict[str, Any] | None
    text_content: str
    created_by: PersonDTO | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SpaceKpiDTO:
    id: UUID
    channel_id: UUID
    name: str
    insight_short_id: str
    position: int
    created_by: PersonDTO | None
    created_at: datetime


@dataclass(frozen=True)
class SpaceHomeDTO:
    docs: list[DocSummaryDTO]
    kpis: list[SpaceKpiDTO]


@dataclass(frozen=True)
class DiscussionPostDTO:
    id: UUID
    content: str
    created_by: PersonDTO | None
    created_at: datetime


@dataclass(frozen=True)
class DiscussionThreadDTO:
    id: UUID
    content: str
    created_by: PersonDTO | None
    created_at: datetime
    anchor_key: str
    anchor_text: str
    resolved: bool
    replies: list[DiscussionPostDTO]


@dataclass(frozen=True)
class CollabSaveResultDTO:
    """What the save did. ``doc`` is set only when the steps were accepted; on a conflict
    ``steps`` and ``client_ids`` carry the range the caller missed."""

    status: CollabSubmitStatus
    version: int
    doc: DocDTO | None = None
    steps: list[dict[str, Any]] | None = None
    client_ids: list[str] | None = None


@dataclass(frozen=True)
class CreateDocInput:
    team_id: int
    user_id: int
    channel_id: UUID
    title: str
    template: str


@dataclass(frozen=True)
class SaveStepsInput:
    team_id: int
    user_id: int
    user_name: str
    doc_id: UUID
    client_id: str
    steps: list[dict[str, Any]]
    version: int
    content: dict[str, Any]
    text_content: str | None = None
    title: str | None = None
    cursor_head: int | None = None


@dataclass(frozen=True)
class PresenceInput:
    team_id: int
    user_id: int
    user_name: str
    doc_id: UUID
    client_id: str
    version: int
    cursor: dict[str, Any]


@dataclass(frozen=True)
class CreateKpiInput:
    team_id: int
    user_id: int
    channel_id: UUID
    name: str
    insight_short_id: str
