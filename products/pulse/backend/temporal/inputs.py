import datetime as dt
import dataclasses
from typing import Final, TypedDict

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"

# The workflow runs in the Temporal sandbox and can't import the heavy mission module or the
# Django ProductBrief model, so these mirror MissionBundle fields and ProductBrief.Status.QUIET
# as plain literals — named here rather than inlined in workflow.py. A drift-guard test asserts
# they still match their sources (test_workflow_agent.py).
# Final so they carry Literal types — MissionBundleDict access in the workflow needs literal keys.
MISSION_SEED_ITEMS_KEY: Final = "seed_items"
MISSION_GOAL_STATUS_KEY: Final = "goal_status"
QUIET_BRIEF_STATUS: Final = "quiet"

# Per-activity execution budgets (start_to_close timeout, max attempts). The workflow uses these
# directly instead of inline literals; config.py sums them into the execution-timeout ceilings so
# the ceiling provably exceeds the worst-case budget and can't drift out of sync.
GATHER_BRIEF_TIMEOUT = dt.timedelta(minutes=5)
GATHER_BRIEF_ATTEMPTS = 2
SYNTHESIZE_TIMEOUT = dt.timedelta(minutes=5)
SYNTHESIZE_ATTEMPTS = 1  # a retry double-spends LLM calls
PREPARE_MISSION_TIMEOUT = dt.timedelta(minutes=5)
PREPARE_MISSION_ATTEMPTS = 2
RUN_AGENT_TIMEOUT = dt.timedelta(minutes=30)
RUN_AGENT_ATTEMPTS = 1  # one sandbox lifetime; a retry double-spends an entire agent run
VALIDATE_PERSIST_TIMEOUT = dt.timedelta(minutes=5)
VALIDATE_PERSIST_ATTEMPTS = 2  # cheap idempotent retry; the expensive agent run is already captured
MARK_STATUS_TIMEOUT = dt.timedelta(minutes=1)
MARK_STATUS_ATTEMPTS = 3  # failed/quiet terminal writes


class MissionBundleDict(TypedDict, total=False):
    """The serialized MissionBundle keys the workflow reads by key. The full schema lives in
    agent.mission.MissionBundle (which run_agent re-validates); this types only what the workflow
    touches, so a renamed key surfaces at the call site rather than deep in the agent run."""

    seed_items: list[dict]
    goal_status: dict | None


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
    bundle: MissionBundleDict


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
