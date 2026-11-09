"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses
from datetime import timedelta

HIGHLIGHTS_WORKFLOW_NAME = "today-compute-highlights"
WRITE_NEWS_WORKFLOW_NAME = "today-news-agent"
WRITE_NEWS_WORKFLOW_TIMEOUT = timedelta(minutes=16)
MAX_NEWS_ERROR_LENGTH = 2000


@dataclasses.dataclass(frozen=True)
class PinnedNumber:
    key: str
    dashboard_id: int | None = None


@dataclasses.dataclass(frozen=True)
class ComputeHighlightsInputs:
    team_id: int
    user_id: int
    highlights_id: str
    local_day: str
    scopes: list[str] | None
    source_names: list[str]
    pins: list[PinnedNumber] = dataclasses.field(default_factory=list)
    hidden: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class HighlightSourceInputs:
    team_id: int
    user_id: int
    local_day: str
    scopes: list[str] | None
    source_name: str
    pinned: list[str] = dataclasses.field(default_factory=list)
    highlights_id: str | None = None
    hidden: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class HighlightSourceResult:
    source_name: str
    found: str | None
    failed: bool


@dataclasses.dataclass(frozen=True)
class ResolvePinsInputs:
    team_id: int
    user_id: int
    local_day: str
    scopes: list[str] | None
    pins: list[PinnedNumber]
    highlights_id: str | None = None


@dataclasses.dataclass(frozen=True)
class ResolvePinsResult:
    found: str
    failed: bool = False


@dataclasses.dataclass(frozen=True)
class FinalizeHighlightsInputs:
    team_id: int
    highlights_id: str
    results: list[HighlightSourceResult]
    pins: list[PinnedNumber] = dataclasses.field(default_factory=list)
    pinned: str = "[]"
    pins_failed: bool = False


def highlights_workflow_id(team_id: int, user_id: int, highlights_id: str) -> str:
    return f"today-highlights-{team_id}-{user_id}-{highlights_id}"


@dataclasses.dataclass(frozen=True)
class WriteNewsInputs:
    team_id: int
    user_id: int
    edition_id: str
    claimed_at: str


@dataclasses.dataclass(frozen=True)
class FailNewsInputs:
    team_id: int
    edition_id: str
    error: str
    claimed_at: str


def write_news_workflow_id(team_id: int, edition_id: str, attempt: int) -> str:
    return f"today-news-agent-{team_id}-{edition_id}-{attempt}"
