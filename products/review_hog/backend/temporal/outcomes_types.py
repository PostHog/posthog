from dataclasses import dataclass

CLASSIFY_FINDING_OUTCOMES_WORKFLOW = "review-classify-finding-outcomes"


@dataclass
class ClassifyFindingOutcomesInputs:
    """Input to the periodic sweep. Carries no window: the sweep classifies whatever discovery
    returns, which is every published report still missing its `outcomes_emitted_at` stamp
    regardless of age."""


@dataclass
class ClassifyTeamOutcomesInputs:
    """Input to the per-team classification activity."""

    team_id: int
