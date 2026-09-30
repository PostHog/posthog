"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses
from typing import Any

GENERATE_WORKFLOW_NAME = "today-generate-briefing"
SCHEDULER_WORKFLOW_NAME = "today-briefing-scheduler"


@dataclasses.dataclass(frozen=True)
class GenerateBriefingInputs:
    team_id: int
    briefing_id: str


@dataclasses.dataclass(frozen=True)
class CollectSourceInputs:
    team_id: int
    briefing_id: str
    source: str


@dataclasses.dataclass(frozen=True)
class DraftInputs:
    team_id: int
    briefing_id: str
    # `Candidate.to_payload()` dicts from the source activities.
    candidates: list[dict[str, Any]]
    failed_sources: list[str]


@dataclasses.dataclass(frozen=True)
class MarkFailedInputs:
    team_id: int
    briefing_id: str
    error: str


@dataclasses.dataclass(frozen=True)
class SchedulerInputs:
    pass


def generate_workflow_id(briefing_id: str) -> str:
    return f"today-briefing-{briefing_id}"
