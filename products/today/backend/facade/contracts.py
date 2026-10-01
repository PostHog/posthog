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
