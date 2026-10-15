"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses

GENERATE_WORKFLOW_NAME = "today-generate-briefing"
SCHEDULER_WORKFLOW_NAME = "today-briefing-scheduler"
HIGHLIGHTS_WORKFLOW_NAME = "today-compute-highlights"


@dataclasses.dataclass(frozen=True)
class GenerateBriefingInputs:
    team_id: int
    briefing_id: str


@dataclasses.dataclass(frozen=True)
class MarkFailedInputs:
    team_id: int
    briefing_id: str
    error: str


@dataclasses.dataclass(frozen=True)
class SchedulerInputs:
    pass


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
class FinalizeHighlightsInputs:
    team_id: int
    highlights_id: str
    results: list[HighlightSourceResult]


def generate_workflow_id(briefing_id: str) -> str:
    return f"today-briefing-{briefing_id}"


def highlights_workflow_id(team_id: int, user_id: int, highlights_id: str) -> str:
    return f"today-highlights-{team_id}-{user_id}-{highlights_id}"
