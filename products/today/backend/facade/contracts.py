"""Contract types for today: what the product returns to its API, MCP tools and other products."""

from datetime import date, datetime

from pydantic.dataclasses import dataclass

from .enums import BriefingEdition, BriefingStatus, BriefingWriter, ItemGroup, ItemReason, ItemSource, ItemState


@dataclass(frozen=True)
class BriefingSegment:
    text: str
    item_key: str | None = None
    highlight: bool = False


@dataclass(frozen=True)
class BriefingItem:
    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    label: str
    signal: str
    url: str
    rank: int
    state: ItemState
    # For a report, the product its signals came from (error_tracking, session_replay, ...), else None.
    source_product: str | None


@dataclass(frozen=True)
class Briefing:
    id: str
    status: BriefingStatus
    writer: BriefingWriter | None
    local_day: date
    edition: BriefingEdition
    headline: str
    paragraphs: list[list[BriefingSegment]]
    items: list[BriefingItem]
    more_reports_count: int
    open_reports_count: int
    created_at: datetime
    ready_at: datetime | None


@dataclass(frozen=True)
class CandidateFact:
    name: str
    value: str


@dataclass(frozen=True)
class Candidate:
    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    url: str
    rank: int
    in_text: bool
    facts: list[CandidateFact]


@dataclass(frozen=True)
class CandidateList:
    local_day: date
    candidates: list[Candidate]
    more_reports_count: int
    failed_sources: list[str]


@dataclass(frozen=True)
class BriefingWriteItem:
    """One item the agent chose for the briefing, in the order it ranked them."""

    key: str
    group: ItemGroup
    source: ItemSource
    reason: ItemReason
    title: str
    label: str
    signal: str
    url: str
    urgency: int
    facts: list[CandidateFact]
    source_product: str | None = None


@dataclass(frozen=True)
class BriefingWrite:
    """The briefing the agent wrote: the text and the items it names, in rank order."""

    briefing_id: str
    headline: str
    paragraphs: list[list[BriefingSegment]]
    items: list[BriefingWriteItem]


class BriefingNotFound(Exception):
    """No briefing with that id belongs to the person."""


class BriefingWriteRejected(Exception):
    """The written briefing broke the rules; `problems` says which, so the writer can fix them."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
