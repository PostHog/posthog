"""Contract types for today: what the product returns to its API, MCP tools and other products."""

from collections.abc import Callable
from dataclasses import field
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
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
    PulseSlotStatus,
    SidebarButtonVariant,
    SidebarIcon,
    SidebarListSource,
    SidebarPage,
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
    # Results stored before this field existed have no product.
    product: str | None = None


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


@frozen
class PulseSlot:
    key: str
    name: str
    reason: HighlightMetricReason | None = None
    status: PulseSlotStatus = PulseSlotStatus.PENDING
    url: str | None = None
    interval: HighlightInterval | None = None


@dataclass(frozen=True)
class Highlights:
    status: HighlightsStatus
    generated_at: datetime | None
    day: date
    refresh_at: datetime
    pulse: list[HighlightMetric]
    items: list[HighlightItem]
    pins: list[HighlightPin] = field(default_factory=list)
    pulse_slots: list[PulseSlot] | None = None


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

    # Unique across products and stable: Today keys stored results and analytics by it, so a rename breaks them.
    name: str
    find: Callable[[HighlightContext], HighlightFindings]
    # Today skips the source when the viewer's API scopes or access controls do not cover these.
    scopes: tuple[str, ...] = ()
    pulse_order: int = 0


# The analytics sidebar: the layout of the Analytics pane in the new navigation. A person or their agent writes it,
# so every value is from a closed set: no URLs, no HTML, no colors, only PostHog pages and objects of the project.

SIDEBAR_SHORT_ID_PATTERN = r"^[A-Za-z0-9]{8}$"
SIDEBAR_SECTION_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SIDEBAR_SECTIONS = 10
MAX_SIDEBAR_SECTION_ITEMS = 12
MAX_SIDEBAR_METRICS = 4

SidebarLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class _SidebarModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SidebarPageTarget(_SidebarModel):
    """A PostHog page. It has its own label and icon."""

    kind: Literal["page"]
    page: SidebarPage


class SidebarInsightTarget(_SidebarModel):
    kind: Literal["insight"]
    short_id: str = Field(
        pattern=SIDEBAR_SHORT_ID_PATTERN, description="The insight's short ID, as in /insights/<short_id>."
    )


class SidebarDashboardTarget(_SidebarModel):
    kind: Literal["dashboard"]
    id: int = Field(ge=1, description="The dashboard's numeric ID.")


class SidebarNotebookTarget(_SidebarModel):
    kind: Literal["notebook"]
    short_id: str = Field(
        pattern=SIDEBAR_SHORT_ID_PATTERN, description="The notebook's short ID, as in /notebooks/<short_id>."
    )


SidebarTarget = Annotated[
    SidebarPageTarget | SidebarInsightTarget | SidebarDashboardTarget | SidebarNotebookTarget,
    Field(discriminator="kind", description="What the item opens. Only pages and objects of this project."),
]


class SidebarLink(_SidebarModel):
    """A row that opens a page or an object."""

    type: Literal["link"]
    to: SidebarTarget
    label: SidebarLabel | None = Field(
        default=None, description="Text of the row. Leave it out for a page to use the page's name. Required otherwise."
    )
    icon: SidebarIcon | None = Field(default=None, description="Icon of the row. A page has its own icon.")

    @model_validator(mode="after")
    def _object_links_have_a_label(self) -> Self:
        if self.label is None and not isinstance(self.to, SidebarPageTarget):
            raise ValueError("A link to an insight, dashboard or notebook needs a label.")
        return self


class SidebarButton(_SidebarModel):
    """A button that opens a page or an object. Use it for an action, such as a new insight."""

    type: Literal["button"]
    to: SidebarTarget
    label: SidebarLabel
    icon: SidebarIcon | None = None
    variant: SidebarButtonVariant = SidebarButtonVariant.OUTLINE


class SidebarMetric(_SidebarModel):
    """The latest value of a trends insight, with a sparkline of its first series. Opens the insight."""

    type: Literal["metric"]
    insight: str = Field(pattern=SIDEBAR_SHORT_ID_PATTERN, description="Short ID of a trends insight.")
    label: SidebarLabel | None = Field(default=None, description="Name of the number. Defaults to the insight's name.")


class SidebarList(_SidebarModel):
    """A list that PostHog fills, such as the items the person pinned."""

    type: Literal["list"]
    source: SidebarListSource


SidebarItem = Annotated[
    SidebarLink | SidebarButton | SidebarMetric | SidebarList,
    Field(discriminator="type"),
]


class SidebarSection(_SidebarModel):
    id: str = Field(
        min_length=1,
        max_length=32,
        pattern=SIDEBAR_SECTION_ID_PATTERN,
        description="Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID.",
    )
    title: SidebarLabel | None = Field(
        default=None,
        description="Heading of the section. A section with a heading can be closed. Without one, its items show at the top.",
    )
    icon: SidebarIcon | None = Field(default=None, description="Icon before the heading.")
    items: list[SidebarItem] = Field(min_length=1, max_length=MAX_SIDEBAR_SECTION_ITEMS)


class AnalyticsSidebarLayout(_SidebarModel):
    """The sections of the Analytics pane, from top to bottom. A section with no items to show is hidden."""

    version: Literal[1] = 1
    sections: list[SidebarSection] = Field(min_length=1, max_length=MAX_SIDEBAR_SECTIONS)

    @model_validator(mode="after")
    def _ids_and_lists_are_unique(self) -> Self:
        ids = [section.id for section in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError("Each section needs its own id.")
        items = [item for section in self.sections for item in section.items]
        sources = [item.source for item in items if isinstance(item, SidebarList)]
        if len(set(sources)) != len(sources):
            raise ValueError("Each list source can show once.")
        if sum(isinstance(item, SidebarMetric) for item in items) > MAX_SIDEBAR_METRICS:
            raise ValueError(f"Show at most {MAX_SIDEBAR_METRICS} metrics.")
        return self


@frozen
class AnalyticsSidebar:
    layout: AnalyticsSidebarLayout
    customized: bool
