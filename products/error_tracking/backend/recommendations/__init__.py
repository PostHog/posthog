from .base import BaseRecommendation
from .cross_sell import CrossSellRecommendation

ALL_RECOMMENDATIONS: list[type[BaseRecommendation]] = [
    CrossSellRecommendation,
]

RECOMMENDATIONS_BY_TYPE: dict[str, type[BaseRecommendation]] = {r.type: r for r in ALL_RECOMMENDATIONS}


__all__ = [
    "ALL_RECOMMENDATIONS",
    "RECOMMENDATIONS_BY_TYPE",
    "BaseRecommendation",
    "CrossSellRecommendation",
]
