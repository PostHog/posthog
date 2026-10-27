"""Contract types for today: what the product returns to its API, MCP tools and other products."""

from collections.abc import Callable
from dataclasses import field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from pydantic.dataclasses import dataclass

from posthog.dataclasses import frozen

from .enums import (
    CitedSource,
    FigureSourceKind,
    FigureText,
    HighlightInterval,
    HighlightLabel,
    HighlightMetricReason,
    HighlightPinStatus,
    HighlightPriority,
    HighlightsStatus,
    HighlightUnit,
    ImpactNumberKey,
    KeyClauseRole,
)

if TYPE_CHECKING:
    from posthog.models import Team, User

T = TypeVar("T")


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


@dataclass(frozen=True)
class HighlightValueFormat:
    format: str | None
    prefix: str | None
    postfix: str | None
    decimal_places: int | None


@dataclass(frozen=True)
class HighlightMover:
    label: str
    value: float
    change_pct: float | None


@dataclass(frozen=True)
class HighlightMetric:
    key: str
    name: str
    value: float
    unit: HighlightUnit
    change_pct: float | None
    series: list[float]
    interval: HighlightInterval = HighlightInterval.DAY
    url: str | None = None
    value_format: HighlightValueFormat | None = None
    period_starts: list[date] = field(default_factory=list)
    reason: HighlightMetricReason | None = None
    dashboard_name: str | None = None
    dashboard_id: int | None = None
    opened_days: int | None = None
    last_opened: date | None = None
    movers: list[HighlightMover] = field(default_factory=list)
    previous_value: float | None = None


@dataclass(frozen=True)
class HighlightItem:
    key: str
    source: str
    label: HighlightLabel
    priority: HighlightPriority
    title: str
    detail: str
    url: str | None
    series: list[float] | None
    score: float


@dataclass(frozen=True)
class PulsePin:
    key: str
    name: str
    dashboard_id: int | None = None


@dataclass(frozen=True)
class PulsePins:
    pins: list[PulsePin]


@dataclass(frozen=True)
class HighlightPin:
    key: str
    status: HighlightPinStatus


@dataclass(frozen=True)
class Highlights:
    status: HighlightsStatus
    generated_at: datetime | None
    day: date
    refresh_at: datetime
    pulse: list[HighlightMetric]
    items: list[HighlightItem]
    pins: list[HighlightPin] = field(default_factory=list)


class DailyValueNotReady(Exception):
    """A source raises this when a value it needs is still being computed. Today retries the source soon."""


@frozen
class HighlightCandidate:
    """One fact a source offers to "For you today". Today ranks every candidate and shows the best few."""

    key: str
    label: HighlightLabel
    # Today shows at most two items of one family, so a product cannot fill the list alone.
    family: str
    importance: float
    relevance: float
    title: str
    detail: str
    url: str | None = None
    series: list[float] | None = None
    # Items of different families that share a ref are about the same object, so Today shows one of them.
    ref: str | None = None
    # Today sets this to the name of the source that found the item.
    source: str = ""


@frozen
class HighlightDetection:
    """A notable move in a series, as `highlight_helpers.detect` reports it."""

    kind: str
    strength: float
    direction: int
    pct: float | None = None
    now: float | None = None
    usual: float | None = None
    weekday: str | None = None
    same_weekday: bool = False


@frozen
class HighlightFindings:
    items: tuple[HighlightCandidate, ...] = ()
    pulse: tuple[HighlightMetric, ...] = ()


class HighlightContext(Protocol):
    """What Today gives a source's `find`: the viewer, their local day, and Today's cache and error guard."""

    team: "Team"
    user: "User"
    today: date

    def allows(self, *required: str) -> bool: ...

    # Caches one value per team, property restrictions and day, so every viewer with the same
    # restrictions shares it. Never compute a per-viewer value here. Prefix `name` with the source name.
    def daily(self, name: str, compute: Callable[[], T]) -> T: ...

    def guard(self, name: str, provider: Callable[[], T], default: T) -> T: ...


@frozen
class HighlightSource:
    """A product's contribution to "For you today".

    A product declares its sources in `HIGHLIGHT_SOURCES` in `backend/facade/today_highlights.py`.
    Today finds that module by name, so a new source changes no file in Today.
    """

    # Unique across products. Today keys stored results and the frontend icon by it.
    name: str
    find: Callable[[HighlightContext], HighlightFindings]
    # Today skips the source when the viewer's API scopes or access controls do not cover these.
    scopes: tuple[str, ...] = ()
    pulse_order: int = 0
