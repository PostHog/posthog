"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses

GENERATE_WORKFLOW_NAME = "today-generate-briefing"
SCHEDULER_WORKFLOW_NAME = "today-briefing-scheduler"


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


def generate_workflow_id(briefing_id: str) -> str:
    return f"today-briefing-{briefing_id}"
