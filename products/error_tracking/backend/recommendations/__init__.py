from .alerts import AlertsRecommendation
from .base import Recommendation
from .long_running_issues import LongRunningIssuesRecommendation
from .source_maps import SourceMapsRecommendation

RECOMMENDATIONS: list[Recommendation] = [
    AlertsRecommendation(),
    LongRunningIssuesRecommendation(),
    SourceMapsRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
