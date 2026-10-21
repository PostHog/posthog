"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses

HIGHLIGHTS_WORKFLOW_NAME = "today-compute-highlights"


@dataclasses.dataclass(frozen=True)
class ComputeHighlightsInputs:
    team_id: int
    user_id: int
    highlights_id: str
    local_day: str
    scopes: list[str] | None
    source_names: list[str]


@dataclasses.dataclass(frozen=True)
class HighlightSourceInputs:
    team_id: int
    user_id: int
    local_day: str
    scopes: list[str] | None
    source_name: str


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
    keys: list[str] | None


@dataclasses.dataclass(frozen=True)
class ResolvePinsResult:
    keys: list[str]
    found: str
    pending: list[str]
    failed: bool


@dataclasses.dataclass(frozen=True)
class FinalizeHighlightsInputs:
    team_id: int
    highlights_id: str
    results: list[HighlightSourceResult]
    pins: list[ResolvePinsResult] = dataclasses.field(default_factory=list)


def highlights_workflow_id(team_id: int, user_id: int, highlights_id: str) -> str:
    return f"today-highlights-{team_id}-{user_id}-{highlights_id}"
