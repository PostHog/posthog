from typing import Any

from posthog.schema import IntervalType

from posthog.dataclasses import frozen
from posthog.tasks.alerts.detectors.pyod_detectors.knn import KNNDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector


@frozen
class AnomalyScoringConfig:
    """Defaults for anomaly scoring. Every value is a plain field, so a flag payload can override it."""

    detector_operator: str = "and"
    hour_lookback: str = "-14d"
    day_lookback: str = "-90d"
    week_lookback: str = "-52w"
    month_lookback: str = "-36m"
    warm_up_points: int = 14
    month_warm_up_points: int = 12
    max_breakdown_values: int = 10
    max_series: int = 20
    max_backfill_buckets: int = 30

    def detector_config(self) -> dict[str, Any]:
        return {
            "type": "ensemble",
            "operator": self.detector_operator,
            "detectors": [ZScoreDetector.get_default_config(), KNNDetector.get_default_config()],
        }

    def lookback_for(self, interval: IntervalType) -> str | None:
        return {
            IntervalType.HOUR: self.hour_lookback,
            IntervalType.DAY: self.day_lookback,
            IntervalType.WEEK: self.week_lookback,
            IntervalType.MONTH: self.month_lookback,
        }.get(interval)

    def warm_up_for(self, interval: IntervalType) -> int:
        return self.month_warm_up_points if interval == IntervalType.MONTH else self.warm_up_points


DEFAULT_CONFIG = AnomalyScoringConfig()
