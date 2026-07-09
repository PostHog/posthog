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
    # "synthesize" (single LLM call) or "agent" (sandbox mission). User-facing generation
    # is agent-only; synthesize remains for the eval command and internal callers.
    engine: str = "synthesize"


@dataclasses.dataclass
class SynthesizeActivityInputs:
    team_id: int
    brief_id: str
    items: list[dict]


@dataclasses.dataclass
class RunAgentInputs:
    team_id: int
    brief_id: str
    bundle: dict


@dataclasses.dataclass
class ValidatePersistInputs:
    team_id: int
    brief_id: str
    # Raw agent report — untrusted until validate_agent_report accepts it.
    report: dict
    agent_session_ref: str
    transcript_key: str | None
    seed_items: list[dict]


@dataclasses.dataclass
class MarkBriefFailedInputs:
    team_id: int
    brief_id: str
    error: str
