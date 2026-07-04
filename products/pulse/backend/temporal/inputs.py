import dataclasses

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"


def pulse_brief_workflow_id(team_id: int, brief_config_id: str | None) -> str:
    """Single-flight workflow id per team+config: any two generation starts for the same
    focus (on-demand API, scheduled subscription) collide as WorkflowAlreadyStartedError.
    Both start sites must mint the id here, never inline."""
    return f"pulse-brief-{team_id}-{brief_config_id or 'default'}"


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
