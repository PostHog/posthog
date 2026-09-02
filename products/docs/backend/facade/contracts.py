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
    DataShape,
    DiscussionKind,
    DocKind,
    DocStatus,
    PostAuthorKind,
    WatchAction,
    WatchActor,
    WatchEvent,
    WatchStatus,
    WatchStopReason,
    WatchVerdict,
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
    """A hypothesis under watch, as the space's home lists it."""

    thread_id: UUID
    doc_id: UUID
    doc_title: str
    anchor_key: str
    anchor_text: str
    status: WatchStatus
    verdict: WatchVerdict
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
    # Set on posts a watch writes, so a timeline reads them without parsing words.
    event: WatchEvent | None = None


@dataclass(frozen=True)
class DataAnswerDTO:
    """The query behind a data point. The page runs it on every read and draws it by its shape."""

    query: str
    label: str
    note: str
    shape: DataShape
    run_id: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class WatchEvidenceDTO:
    """One number the claim stands on, with where it stands against its baseline."""

    label: str
    query: str
    shape: DataShape
    baseline: float | None
    value: float | None
    checked_at: datetime | None
    error: str | None
    history: list[list[Any]]
    moved: bool


@dataclass(frozen=True)
class WatchBriefDTO:
    """What the agent compiled the claim into: the claim, what decides it, the evidence, the signals."""

    claim: str
    confirms: str
    refutes: str
    evidence: list[WatchEvidenceDTO]
    signals: list[str]
    submitted_at: datetime | None


@dataclass(frozen=True)
class WatchVerdictDTO:
    verdict: WatchVerdict
    reason: str
    by: WatchActor
    at: datetime | None


@dataclass(frozen=True)
class WatchScoutDTO:
    """The scout that follows the hypothesis's signals."""

    config_id: str
    skill_name: str


@dataclass(frozen=True)
class DocWatchDTO:
    """The watch on a thread: whether it runs, what it stands on, and where the claim stands."""

    status: WatchStatus
    stopped_reason: WatchStopReason | None
    verdict: WatchVerdictDTO
    brief: WatchBriefDTO | None
    scout: WatchScoutDTO | None
    scout_error: str | None
    next_check_at: datetime | None
    checked_at: datetime | None
    evidence_only: bool = False


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
    watch: DocWatchDTO | None = None


@dataclass(frozen=True)
class ReplyResultDTO:
    thread: DiscussionThreadDTO
    delivery: AgentDelivery


@dataclass(frozen=True)
class WatchEvidenceInput:
    label: str
    query: str


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
    # A watch on a number already on the page: the brief is the query, and no scout runs.
    evidence: list[WatchEvidenceInput] = Field(default_factory=list)


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
    shape: DataShape | None
    value: str | None
    rows: int
    columns: int
    error: str | None


@dataclass(frozen=True)
class SubmitWatchBriefInput:
    """An agent handing in the brief behind a watch. ``task_id`` is the run's own, from its token."""

    team_id: int
    task_id: str
    request_id: str
    claim: str
    confirms: str
    refutes: str
    evidence: list[WatchEvidenceInput]
    signals: list[str]


@dataclass(frozen=True)
class WatchEvidenceResultDTO:
    label: str
    ok: bool
    value: str | None
    error: str | None


@dataclass(frozen=True)
class SubmitWatchBriefResultDTO:
    ok: bool
    evidence: list[WatchEvidenceResultDTO]
    error: str | None


@dataclass(frozen=True)
class SubmitWatchVerdictInput:
    team_id: int
    task_id: str
    request_id: str
    verdict: WatchVerdict
    reason: str


@dataclass(frozen=True)
class WatchActionInput:
    """What a person does to a watch from its thread."""

    team_id: int
    user_id: int
    doc_id: UUID
    thread_id: UUID
    action: WatchAction
    verdict: WatchVerdict | None = None
    reason: str = ""


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
