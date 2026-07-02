import dataclasses

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"


@dataclasses.dataclass
class GenerateBriefWorkflowInputs:
    team_id: int
    brief_id: str
    brief_config_id: str | None = None
    period_days: int = 7


@dataclasses.dataclass
class SynthesizeActivityInputs:
    team_id: int
    brief_id: str
    items: list[dict]


@dataclasses.dataclass
class MarkBriefFailedInputs:
    team_id: int
    brief_id: str
    error: str
