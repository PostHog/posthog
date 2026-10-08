"""Workflow names and inputs. Light on purpose: the API imports this to start workflows."""

import dataclasses

DISCOVERY_WORKFLOW_NAME = "metrics-suggested-dashboards-discovery"
SUGGEST_WORKFLOW_NAME = "metrics-suggested-dashboards-suggest"
GENERATE_WORKFLOW_NAME = "metrics-suggested-dashboards-generate"


@dataclasses.dataclass(frozen=True)
class DiscoveryInputs:
    pass


@dataclasses.dataclass(frozen=True)
class SuggestInputs:
    team_id: int
    # Analyze even when no metric name is new and the bank did not change.
    force: bool = False


@dataclasses.dataclass(frozen=True)
class GenerationRequestInputs:
    key: str
    name: str
    description: str
    metric_names: list[str]


@dataclasses.dataclass(frozen=True)
class SuggestResult:
    suggestion_count: int
    generation_requests: list[GenerationRequestInputs]


@dataclasses.dataclass(frozen=True)
class GenerateInputs:
    team_id: int
    request: GenerationRequestInputs


@dataclasses.dataclass(frozen=True)
class RoundInputs:
    template_id: str
    round: int
    revise: bool = True


@dataclasses.dataclass(frozen=True)
class FinishInputs:
    template_id: str
    error: str | None = None


def suggest_workflow_id(team_id: int) -> str:
    return f"metrics-suggested-dashboards-suggest-{team_id}"


def generate_workflow_id(key: str) -> str:
    return f"metrics-suggested-dashboards-generate-{key}"
