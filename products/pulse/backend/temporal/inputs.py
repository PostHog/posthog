import dataclasses

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"
RESEARCH_OPPORTUNITY_WORKFLOW_NAME = "pulse-research-opportunity"


def pulse_brief_workflow_id(team_id: int, brief_config_id: str | None) -> str:
    """Single-flight workflow id per team+config: any two generation starts for the same
    focus (on-demand API, scheduled subscription) collide as WorkflowAlreadyStartedError.
    Both start sites must mint the id here, never inline."""
    return f"pulse-brief-{team_id}-{brief_config_id or 'default'}"


def pulse_research_workflow_id(team_id: int, opportunity_id: str) -> str:
    """Single-flight workflow id per team+opportunity: a second research run for the same
    opportunity while one is in flight collides as WorkflowAlreadyStartedError. A closed run's
    id is reusable, so re-researching a completed opportunity works."""
    return f"pulse-research-{team_id}-{opportunity_id}"


@dataclasses.dataclass
class GenerateBriefWorkflowInputs:
    team_id: int
    brief_id: str
    brief_config_id: str | None = None
    period_days: int = 7


@dataclasses.dataclass
class ReplayPatternsActivityInputs:
    team_id: int
    brief_id: str
    items: list[dict]


@dataclasses.dataclass
class SynthesizeActivityInputs:
    team_id: int
    brief_id: str
    items: list[dict]
    # Replay-pattern findings computed in their own activity (group summarization runs minutes,
    # past the investigate stage deadline), merged into the investigation before synthesis.
    replay_findings: list[dict] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class MarkBriefFailedInputs:
    team_id: int
    brief_id: str
    error: str


@dataclasses.dataclass
class ResearchOpportunityWorkflowInputs:
    team_id: int
    opportunity_id: str
    # The requesting user: the notebook is created under them and drives LLM billing attribution.
    user_id: int
