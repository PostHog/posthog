from .alerts import AlertsRecommendation
from .base import Recommendation

RECOMMENDATIONS: list[Recommendation] = [
    AlertsRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
