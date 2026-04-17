from .base import Recommendation
from .cross_sell import CrossSellRecommendation

RECOMMENDATIONS: list[Recommendation] = [
    CrossSellRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
