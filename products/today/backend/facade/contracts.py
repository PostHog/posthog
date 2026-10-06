"""Contract types for today: what the product returns to its API, MCP tools and other products."""

from datetime import date, datetime
from typing import Any

from pydantic.dataclasses import dataclass

from .enums import (
    BriefingStatus,
    BriefingWriter,
    CitedSource,
    FigureSourceKind,
    FigureText,
    FocusDirection,
    ImpactNumberKey,
    ItemGroup,
    ItemReason,
    ItemSource,
    ItemState,
    KeyClauseRole,
)


@dataclass(frozen=True)
class FocusTopic:
    topic: str
    direction: FocusDirection


@dataclass(frozen=True)
class BriefingFocus:
    """What a person asked their briefing to show more or less of, by source product."""

    topics: list[FocusTopic]


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


@dataclass(frozen=True)
class PullRequestLink:
    url: str
    number: int


@dataclass(frozen=True)
class CodeFile:
    repo: str
    path: str


@dataclass(frozen=True)
class PreviewLine:
    text: str
    quiet: bool


@dataclass(frozen=True)
class PageLink:
    url: str
    text: str


@dataclass(frozen=True)
class SignalPreview:
    hint: str
    code: list[CodeFile]
    block: list[PreviewLine]
    text: str
    facts: list[str]
    link: PageLink | None
    link_label: str | None


@dataclass(frozen=True)
class RecordingTarget:
    session_id: str
    start_at: datetime | None
    offset: str | None
    seek_seconds: int | None


@dataclass(frozen=True)
class SignalView:
    signal_id: str
    source_product: str
    source_type: str
    source_id: str
    content: str
    timestamp: datetime
    extra: dict[str, Any]
    headline: str
    lead: str
    meta: str
    cited: CitedSource | None
    recording: RecordingTarget | None
    link: PageLink | None
    preview: SignalPreview | None


@dataclass(frozen=True)
class ImpactWorking:
    expression: str
    result: str


@dataclass(frozen=True)
class ImpactNumber:
    key: ImpactNumberKey
    value: str
    sentence: str
    signal: SignalView | None
    values: list[str]
    working: ImpactWorking | None


@dataclass(frozen=True)
class ReportPage:
    lead: str
    proposal: str
    impact_sentence: str
    named_pull_request: PullRequestLink | None
    solution_names_pull_request: bool
    evidence: list[SignalView]
    source_count: int
    impact_numbers: list[ImpactNumber]
    last_seen: datetime | None


@dataclass(frozen=True)
class KeyClause:
    start: int
    end: int
    role: KeyClauseRole
    expansion: list[str]


@dataclass(frozen=True)
class ReportKeyClauses:
    lead: list[KeyClause]
    impact: list[KeyClause]
    proposal: list[KeyClause]


@dataclass(frozen=True)
class FigureQuote:
    kind: FigureSourceKind
    signal: SignalView | None
    at: datetime
    sentence: str
    start: int
    end: int


@dataclass(frozen=True)
class FigureMark:
    text: FigureText
    start: int
    end: int
    figure: str
    quote: FigureQuote


class JevTimedOut(Exception):
    pass
