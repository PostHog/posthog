from typing import TYPE_CHECKING, Any

from posthog.schema import IntervalType

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import Team

    from products.product_analytics.backend.facade.models import Insight


@frozen
class IntervalScoring:
    """How one interval is scored. The detector is any registered detector config, so swapping it needs no code."""

    lookback: str
    min_points: int
    detector: dict[str, Any]


@frozen
class ScoringProfile:
    name: str
    intervals: dict[IntervalType, IntervalScoring]

    def for_interval(self, interval: IntervalType) -> IntervalScoring | None:
        return self.intervals.get(interval)


@frozen
class ScoringLimits:
    """Caps that bound the cost of scoring one insight. Every value is a plain field, so a flag payload can override it."""

    max_breakdown_values: int = 10
    max_series: int = 20
    max_backfill_buckets: int = 30


def _zscore(window: int) -> dict[str, Any]:
    # diffs_n is set explicitly: when preprocessing is given without it, the detector scores raw values,
    # and on sparse series raw values score almost every non-zero bucket near 1.0.
    return {"type": "zscore", "threshold": 0.95, "window": window, "preprocessing": {"diffs_n": 1, "smooth_n": 3}}


DEFAULT_PROFILE = ScoringProfile(
    name="default-v1",
    intervals={
        IntervalType.HOUR: IntervalScoring(lookback="-28d", min_points=336, detector=_zscore(336)),
        IntervalType.DAY: IntervalScoring(lookback="-365d", min_points=56, detector=_zscore(56)),
        IntervalType.WEEK: IntervalScoring(lookback="-156w", min_points=52, detector=_zscore(52)),
        IntervalType.MONTH: IntervalScoring(lookback="-60m", min_points=24, detector=_zscore(24)),
    },
)

DEFAULT_LIMITS = ScoringLimits()


def resolve_profile(team: "Team", insight: "Insight") -> ScoringProfile:
    """The one place that picks scoring settings for an insight, so project and per-metric overrides only change this."""
    return DEFAULT_PROFILE
