from .alerts import AlertsRecommendation
from .base import Recommendation
from .long_running_issues import LongRunningIssuesRecommendation

RECOMMENDATIONS: list[Recommendation] = [
    AlertsRecommendation(),
    LongRunningIssuesRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
