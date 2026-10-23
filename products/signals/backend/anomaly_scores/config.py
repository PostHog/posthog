"""Scoring settings, and the levers of the scheduled tick, read from the `anomaly-scoring` flag payload.

The payload parse fails closed: a missing, malformed or unreadable payload turns the tick off. An invalid
field falls back to its default, and no default is unbounded.
"""

import uuid
import dataclasses
from typing import TYPE_CHECKING, Any

import structlog

from posthog.schema import IntervalType

from posthog.dataclasses import frozen

from products.signals.backend.scout_harness.team_limits import read_flag_payload

if TYPE_CHECKING:
    from posthog.models import Team

    from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

ANOMALY_SCORING_FLAG = "anomaly-scoring"
# Not a person: the flag must serve its payload to this id.
ANOMALY_SCORING_FLAG_DISTINCT_ID = "signals_anomaly_scoring"


@frozen
class IntervalScoring:
    """How one interval is scored. The detector is any registered detector config, so swapping it needs no code."""

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
        IntervalType.HOUR: IntervalScoring(min_points=336, detector=_zscore(336)),
        IntervalType.DAY: IntervalScoring(min_points=56, detector=_zscore(56)),
        IntervalType.WEEK: IntervalScoring(min_points=52, detector=_zscore(52)),
        IntervalType.MONTH: IntervalScoring(min_points=24, detector=_zscore(24)),
    },
)

DEFAULT_LIMITS = ScoringLimits()
# The largest value a flag payload can set for each limit.
MAX_LIMITS = ScoringLimits(max_breakdown_values=25, max_series=50, max_backfill_buckets=90)


def resolve_profile(team: "Team", insight: "Insight") -> ScoringProfile:
    """The one place that picks scoring settings for an insight, so project and per-metric overrides only change this."""
    return DEFAULT_PROFILE


# Hourly insights are left out by default: with many eligible insights, the time between two visits of
# one insight passes the hourly backfill cap, and the buckets in between are never scored.
DEFAULT_TICK_INTERVALS = (IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH)


@frozen
class AnomalyScoringConfig:
    enabled: bool = False
    organization_ids: tuple[str, ...] = ()
    # Empty means every team of the organizations in `organization_ids`.
    allow_team_ids: tuple[int, ...] = ()
    skip_team_ids: tuple[int, ...] = ()
    intervals: tuple[IntervalType, ...] = DEFAULT_TICK_INTERVALS
    # Smooths the spend over the hour, so one tick cannot use the whole query budget.
    max_insights_per_tick: int = 8
    max_concurrency: int = 2
    # Scoring queries per clock hour. One pick sends one query per series, see `scoring.query_cost`.
    max_queries_per_hour: int = 120
    max_queries_per_project_per_hour: int = 30
    limits: ScoringLimits = DEFAULT_LIMITS


DISABLED = AnomalyScoringConfig()
# The largest value a flag payload can set for each lever of the tick.
MAX_INSIGHTS_PER_TICK = 50
MAX_CONCURRENCY = 8
MAX_QUERIES_PER_HOUR = 2000
MAX_QUERIES_PER_PROJECT_PER_HOUR = 500


def _positive_int(value: Any, default: int) -> int:
    # `bool` is an `int` subclass, and `true` is not a count.
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _team_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _organization_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    # A value that is not a UUID would fail the organization lookup of the whole tick.
    return tuple(item for item in value if isinstance(item, str) and _is_uuid(item))


def _intervals(value: Any) -> tuple[IntervalType, ...]:
    if not isinstance(value, list):
        return DEFAULT_TICK_INTERVALS
    scored = {interval.value: interval for interval in DEFAULT_PROFILE.intervals}
    intervals = tuple(dict.fromkeys(scored[item] for item in value if isinstance(item, str) and item in scored))
    return intervals or DEFAULT_TICK_INTERVALS


def parse_limits(payload: Any) -> ScoringLimits:
    """The `limits` object of the payload. An invalid field gets its default, a large one its `MAX_LIMITS` value."""
    if not isinstance(payload, dict):
        return DEFAULT_LIMITS
    return ScoringLimits(
        **{
            field.name: min(
                _positive_int(payload.get(field.name), getattr(DEFAULT_LIMITS, field.name)),
                getattr(MAX_LIMITS, field.name),
            )
            for field in dataclasses.fields(ScoringLimits)
        }
    )


def parse_config(payload: Any) -> AnomalyScoringConfig:
    if not isinstance(payload, dict) or payload.get("enabled") is not True:
        return DISABLED
    defaults = AnomalyScoringConfig()
    return AnomalyScoringConfig(
        enabled=True,
        organization_ids=_organization_ids(payload.get("organization_ids")),
        allow_team_ids=_team_ids(payload.get("allow_team_ids")),
        skip_team_ids=_team_ids(payload.get("skip_team_ids")),
        intervals=_intervals(payload.get("intervals")),
        max_insights_per_tick=min(
            _positive_int(payload.get("max_insights_per_tick"), defaults.max_insights_per_tick), MAX_INSIGHTS_PER_TICK
        ),
        max_concurrency=min(_positive_int(payload.get("max_concurrency"), defaults.max_concurrency), MAX_CONCURRENCY),
        max_queries_per_hour=min(
            _positive_int(payload.get("max_queries_per_hour"), defaults.max_queries_per_hour), MAX_QUERIES_PER_HOUR
        ),
        max_queries_per_project_per_hour=min(
            _positive_int(payload.get("max_queries_per_project_per_hour"), defaults.max_queries_per_project_per_hour),
            MAX_QUERIES_PER_PROJECT_PER_HOUR,
        ),
        limits=parse_limits(payload.get("limits")),
    )


def read_payload() -> dict | None:
    return read_flag_payload(ANOMALY_SCORING_FLAG, ANOMALY_SCORING_FLAG_DISTINCT_ID)


def read_config(payload: Any) -> AnomalyScoringConfig:
    config = parse_config(payload)
    logger.info(
        "anomaly_scoring_config_read",
        enabled=config.enabled,
        organizations=len(config.organization_ids),
        allow_teams=len(config.allow_team_ids),
    )
    return config
