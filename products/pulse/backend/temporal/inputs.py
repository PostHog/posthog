import dataclasses

# Shared by the API (workflow start) and the worker (workflow defn) — this module stays
# light so the web router path never drags in the LLM stack.
GENERATE_BRIEF_WORKFLOW_NAME = "pulse-generate-brief"


def _default_period() -> dict:
    return {"type": "last_n_days", "days": 7}


@dataclasses.dataclass
class GenerateBriefWorkflowInputs:
    team_id: int
    brief_id: str
    brief_config_id: str | None = None
    # Period spec resolved to explicit dates inside the gather activity; shape matches
    # models.default_period (e.g. {"type": "last_n_days", "days": 7} | {"type": "since_last_run"}).
    period: dict = dataclasses.field(default_factory=_default_period)


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
