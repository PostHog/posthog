"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses

HIGHLIGHTS_WORKFLOW_NAME = "today-compute-highlights"


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


@dataclasses.dataclass(frozen=True)
class HighlightSourceInputs:
    team_id: int
    user_id: int
    local_day: str
    scopes: list[str] | None
    source_name: str
    pinned: list[str] = dataclasses.field(default_factory=list)


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


@dataclasses.dataclass(frozen=True)
class ResolvePinsResult:
    found: str


@dataclasses.dataclass(frozen=True)
class FinalizeHighlightsInputs:
    team_id: int
    highlights_id: str
    results: list[HighlightSourceResult]
    pins: list[PinnedNumber] = dataclasses.field(default_factory=list)
    pinned: str = "[]"


def highlights_workflow_id(team_id: int, user_id: int, highlights_id: str) -> str:
    return f"today-highlights-{team_id}-{user_id}-{highlights_id}"
