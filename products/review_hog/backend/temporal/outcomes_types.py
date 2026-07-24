from dataclasses import dataclass

from products.review_hog.backend.reviewer.constants import OUTCOME_LOOKBACK_DAYS

CLASSIFY_FINDING_OUTCOMES_WORKFLOW = "review-classify-finding-outcomes"


@dataclass
class ClassifyFindingOutcomesInputs:
    """Input to the periodic sweep: how far back to look for merged PRs."""

    lookback_days: int = OUTCOME_LOOKBACK_DAYS


@dataclass
class ClassifyTeamOutcomesInputs:
    """Input to the per-team classification activity."""

    team_id: int
    lookback_days: int = OUTCOME_LOOKBACK_DAYS
