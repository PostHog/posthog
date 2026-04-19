from .alerts import AlertsRecommendation
from .base import Recommendation
from .cross_sell import CrossSellRecommendation
from .exception_autocapture import ExceptionAutocaptureRecommendation
from .weekly_digest import WeeklyDigestRecommendation

RECOMMENDATIONS: list[Recommendation] = [
    CrossSellRecommendation(),
    AlertsRecommendation(),
    WeeklyDigestRecommendation(),
    ExceptionAutocaptureRecommendation(),
]

RECOMMENDATIONS_BY_TYPE: dict[str, Recommendation] = {r.type: r for r in RECOMMENDATIONS}
