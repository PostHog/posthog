import dataclasses

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"

# The workflow runs in the Temporal sandbox and can't import the heavy mission module or the
# Django ProductBrief model, so these mirror MissionBundle fields and ProductBrief.Status.QUIET
# as plain literals — named here rather than inlined in workflow.py. A drift-guard test asserts
# they still match their sources (test_workflow_agent.py).
MISSION_SEED_ITEMS_KEY = "seed_items"
MISSION_GOAL_STATUS_KEY = "goal_status"
QUIET_BRIEF_STATUS = "quiet"


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
    # is agent-only; synthesize remains for internal callers.
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
    # Whether a goal block was actually rendered into the mission prompt (goal_status present).
    # Mirrors synthesize's `goal_status is None` check so goalless zeroing is symmetric across
    # engines even when the goal collector degrades to no status.
    has_goal: bool = False


@dataclasses.dataclass
class MarkBriefFailedInputs:
    team_id: int
    brief_id: str
    error: str


@dataclasses.dataclass
class MarkBriefQuietInputs:
    team_id: int
    brief_id: str
    # Human-readable "why this week was quiet" copy, stored on the brief for the user.
    reason: str
