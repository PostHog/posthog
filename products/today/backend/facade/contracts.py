"""Contract types for today: what the product returns to its API, MCP tools and other products."""

from datetime import date, datetime
from typing import Any

from pydantic.dataclasses import dataclass

from .enums import BriefingStatus, BriefingWriter, ItemGroup, ItemReason, ItemSource, ItemState


@dataclass(frozen=True)
class BriefingSegment:
    text: str
    item_key: str | None = None
    highlight: bool = False


@dataclass(frozen=True)
class BriefingItemMetric:
    """A report metric's saved snapshot and its live query. The same fields as the inbox list's metric."""

    metric_id: str
    title: str
    kind: str
    role: str
    value: float
    series: list[float] | None
    value_format: str
    unit: str | None
    query: dict[str, Any]


@dataclass(frozen=True)
class BriefingItemChart:
    """A chart from the report body. The hover card draws it when the report has no metric to chart."""

    chart_id: str
    title: str
    query: dict[str, Any]


@dataclass(frozen=True)
class BriefingItemReport:
    """What the left bar's hover card shows for a report, read live with the item's state."""

    priority: str | None
    summary: str
    pull_request_state: str | None
    pull_request_url: str | None
    signal_count: int
    updated_at: datetime
    metrics: list[BriefingItemMetric]
    charts: list[BriefingItemChart]


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
    # For a report that still exists, its live details, else None.
    report: BriefingItemReport | None


@dataclass(frozen=True)
class Briefing:
    id: str
    status: BriefingStatus
    writer: BriefingWriter | None
    local_day: date
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
    facts: list[CandidateFact]


@dataclass(frozen=True)
class CandidateList:
    local_day: date
    candidates: list[Candidate]
    more_reports_count: int
