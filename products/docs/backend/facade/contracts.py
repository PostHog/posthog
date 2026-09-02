"""
Contract types for docs.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field
from pydantic.dataclasses import dataclass

from .enums import (
    AgentDelivery,
    CollabSubmitStatus,
    DataPointStatus,
    DiscussionKind,
    DocKind,
    DocStatus,
    PostAuthorKind,
)


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
    excerpt: str = ""
    open_thread_count: int = 0
    watch_count: int = 0
    kind: DocKind = DocKind.PAGE


@dataclass(frozen=True)
class WatchSummaryDTO:
    """A section under watch, as the space's context page lists it."""

    doc_id: UUID
    doc_title: str
    anchor_key: str
    anchor_text: str
    loop_id: str | None
    last_report: str
    last_report_at: datetime | None
    created_at: datetime


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
    excerpt: str = ""
    open_thread_count: int = 0
    watch_count: int = 0
    kind: DocKind = DocKind.PAGE


@dataclass(frozen=True)
class SpaceHomeDTO:
    docs: list[DocSummaryDTO]
    watches: list[WatchSummaryDTO] = Field(default_factory=list)


@dataclass(frozen=True)
class DiscussionPostDTO:
    id: UUID
    content: str
    created_by: PersonDTO | None
    created_at: datetime
    author_kind: PostAuthorKind = PostAuthorKind.HUMAN
    sent_to_agent: bool = False


@dataclass(frozen=True)
class DataAnswerDTO:
    """The query behind a data point. The page runs it on every read."""

    query: str
    label: str
    note: str
    run_id: str | None
    updated_at: datetime | None


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
    kind: DiscussionKind = DiscussionKind.TEXT
    task_id: str | None = None
    answer: DataAnswerDTO | None = None
    author_kind: PostAuthorKind = PostAuthorKind.HUMAN
    sent_to_agent: bool = False
    loop_id: str | None = None


@dataclass(frozen=True)
class ReplyResultDTO:
    thread: DiscussionThreadDTO
    delivery: AgentDelivery


@dataclass(frozen=True)
class CreateThreadInput:
    team_id: int
    user_id: int
    doc_id: UUID
    content: str
    anchor_key: str
    anchor_text: str
    kind: DiscussionKind = DiscussionKind.TEXT
    task_id: str | None = None
    send_to_agent: bool = False
    loop_id: str | None = None


@dataclass(frozen=True)
class ReplyInput:
    team_id: int
    user_id: int
    doc_id: UUID
    thread_id: UUID
    content: str
    task_id: str | None = None
    send_to_agent: bool = False


@dataclass(frozen=True)
class SubmitDataPointInput:
    """An agent handing in the query behind a data point. ``task_id`` is the run's own, from its token."""

    team_id: int
    task_id: str
    request_id: str
    status: DataPointStatus
    query: str
    label: str
    note: str


@dataclass(frozen=True)
class SubmitDataPointResultDTO:
    ok: bool
    value: str | None
    error: str | None


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
