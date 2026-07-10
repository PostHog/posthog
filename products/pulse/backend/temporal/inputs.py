import dataclasses

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"


def pulse_brief_workflow_id(team_id: int, brief_config_id: str | None, mission: str = "general_brief") -> str:
    """Single-flight workflow id per team+config+mission: any two generation starts for the
    same focus and mission (on-demand API, scheduled subscription) collide as
    WorkflowAlreadyStartedError, while a query-perf run never 409s against a running general
    brief. Both start sites must mint the id here, never inline."""
    # The default mission keeps the historical id shape so in-flight workflows still collide
    # across a deploy.
    suffix = f"-{mission}" if mission != "general_brief" else ""
    return f"pulse-brief-{team_id}-{brief_config_id or 'default'}{suffix}"


@dataclasses.dataclass
class GenerateBriefWorkflowInputs:
    team_id: int
    brief_id: str
    brief_config_id: str | None = None
    period_days: int = 7
    # "synthesize" (single LLM call) or "agent" (sandbox mission). User-facing generation
    # is agent-only; synthesize remains for the eval command and internal callers.
    engine: str = "synthesize"
    # Key into MISSION_BUILDERS (agent engine only). The generate endpoint staff-gates
    # non-default missions; workflows never check permissions themselves.
    mission: str = "general_brief"


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
