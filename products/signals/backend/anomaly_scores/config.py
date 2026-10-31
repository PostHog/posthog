"""Scoring settings, and the levers of the scheduled tick, read from the `anomaly-scoring` flag payload.

The payload parse fails closed: a missing, malformed or unreadable payload turns the tick off. An invalid
field falls back to its default, and no default is unbounded.
"""

import uuid
import hashlib
import dataclasses
from enum import StrEnum
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


class ScoringRun(StrEnum):
    """The kind of visit when the train and score split is on."""

    # Fetch the training history, fit and store one artifact per series, and score the new buckets with them.
    TRAIN = "train"
    # Fetch only the new buckets and the context that preprocessing reads, and score them with the stored artifacts.
    SCORE = "score"


# Retrain hourly insights once a day, daily once a week, weekly once a month, and monthly once a quarter.
DEFAULT_TRAIN_EVERY_BUCKETS = {IntervalType.HOUR: 24, IntervalType.DAY: 7, IntervalType.WEEK: 4, IntervalType.MONTH: 3}
MAX_TRAIN_EVERY_BUCKETS = {IntervalType.HOUR: 168, IntervalType.DAY: 30, IntervalType.WEEK: 13, IntervalType.MONTH: 12}
# Past `train_every_buckets`, a model keeps scoring until a train step has budget for it. Past this age it stops
# scoring, and its insight waits for a train step. A value at or below `train_every_buckets` turns off stale scores.
DEFAULT_MAX_MODEL_AGE_BUCKETS = {
    IntervalType.HOUR: 96,
    IntervalType.DAY: 28,
    IntervalType.WEEK: 16,
    IntervalType.MONTH: 12,
}
MAX_MODEL_AGE_BUCKETS_LIMIT = {
    IntervalType.HOUR: 672,
    IntervalType.DAY: 120,
    IntervalType.WEEK: 52,
    IntervalType.MONTH: 48,
}


# Hourly insights are left out by default: with many eligible insights, the time between two visits of
# one insight passes the hourly backfill cap, and the buckets in between are never scored.
DEFAULT_TICK_INTERVALS = (IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH)


@frozen
class AnomalyScoringConfig:
    enabled: bool = False
    organization_ids: tuple[str, ...] = ()
    # Empty means every team of the organizations in `organization_ids`. The percentage rollout ignores it.
    allow_team_ids: tuple[int, ...] = ()
    # Scores this percentage of the organizations with a project that has an enabled signal source.
    # Only those projects are scored. A higher percentage keeps the organizations of a lower one.
    self_driving_organization_percentage: float = 0.0
    # The tick never scores these organizations, even when another field enrolls them.
    deny_organization_ids: tuple[str, ...] = ()
    skip_team_ids: tuple[int, ...] = ()
    intervals: tuple[IntervalType, ...] = DEFAULT_TICK_INTERVALS
    # Smooths the spend over the hour, so one tick cannot use the whole query budget. With the split on,
    # the two passes use the per-pass caps below instead.
    max_insights_per_tick: int = 8
    max_concurrency: int = 2
    # Scoring queries per clock hour. One pick sends one query per series, see `scoring.query_cost`.
    max_queries_per_hour: int = 120
    max_queries_per_project_per_hour: int = 30
    limits: ScoringLimits = DEFAULT_LIMITS
    # Off keeps one full fetch per visit and stores no state. On, most visits are cheap score steps.
    train_score_split: bool = False
    train_every_buckets: dict[IntervalType, int] = dataclasses.field(
        default_factory=lambda: dict(DEFAULT_TRAIN_EVERY_BUCKETS)
    )
    max_model_age_buckets: dict[IntervalType, int] = dataclasses.field(
        default_factory=lambda: dict(DEFAULT_MAX_MODEL_AGE_BUCKETS)
    )
    # Score step queries per clock hour. Train steps use the budgets above, so a cheap score step never waits for them.
    max_score_queries_per_hour: int = 600
    max_score_queries_per_project_per_hour: int = 500
    # Per-tick picks of each pass when the split is on. Score steps are cheap, so the score pass gets most slots.
    max_score_insights_per_tick: int = 20
    max_train_insights_per_tick: int = 2
    # An insight is scored only while one of its activity signals falls in this many days, see `queue.active_insights`.
    active_window_days: int = 90


DISABLED = AnomalyScoringConfig()
# The largest value a flag payload can set for each lever of the tick.
MAX_INSIGHTS_PER_TICK = 50
MAX_CONCURRENCY = 8
MAX_QUERIES_PER_HOUR = 2000
MAX_QUERIES_PER_PROJECT_PER_HOUR = 500
MAX_SCORE_QUERIES_PER_HOUR = 5000
MAX_SCORE_QUERIES_PER_PROJECT_PER_HOUR = 1000
MAX_SCORE_INSIGHTS_PER_TICK = 200
MAX_TRAIN_INSIGHTS_PER_TICK = 50
MAX_ACTIVE_WINDOW_DAYS = 365


def _positive_int(value: Any, default: int) -> int:
    # `bool` is an `int` subclass, and `true` is not a count.
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _percentage(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100:
        return default
    return float(value)


def _team_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def _canonical_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _organization_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    # A value that is not a UUID would fail the organization lookup of the whole tick. The canonical form
    # lets `covers_team` compare ids as strings, so an id in another UUID format still matches.
    ids = (_canonical_uuid(item) for item in value if isinstance(item, str))
    return tuple(item for item in ids if item is not None)


def _intervals(value: Any) -> tuple[IntervalType, ...]:
    if not isinstance(value, list):
        return DEFAULT_TICK_INTERVALS
    scored = {interval.value: interval for interval in DEFAULT_PROFILE.intervals}
    intervals = tuple(dict.fromkeys(scored[item] for item in value if isinstance(item, str) and item in scored))
    return intervals or DEFAULT_TICK_INTERVALS


def _buckets_per_interval(
    value: Any, defaults: dict[IntervalType, int], maxima: dict[IntervalType, int]
) -> dict[IntervalType, int]:
    """An object of interval name to bucket count. A missing or invalid count gets its default, a large one its maximum."""
    if not isinstance(value, dict):
        return dict(defaults)
    return {
        interval: min(_positive_int(value.get(interval.value), default), maxima[interval])
        for interval, default in defaults.items()
    }


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
        self_driving_organization_percentage=_percentage(
            payload.get("self_driving_organization_percentage"), defaults.self_driving_organization_percentage
        ),
        deny_organization_ids=_organization_ids(payload.get("deny_organization_ids")),
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
        train_score_split=payload.get("train_score_split") is True,
        train_every_buckets=_buckets_per_interval(
            payload.get("train_every_buckets"), DEFAULT_TRAIN_EVERY_BUCKETS, MAX_TRAIN_EVERY_BUCKETS
        ),
        max_model_age_buckets=_buckets_per_interval(
            payload.get("max_model_age_buckets"), DEFAULT_MAX_MODEL_AGE_BUCKETS, MAX_MODEL_AGE_BUCKETS_LIMIT
        ),
        max_score_queries_per_hour=min(
            _positive_int(payload.get("max_score_queries_per_hour"), defaults.max_score_queries_per_hour),
            MAX_SCORE_QUERIES_PER_HOUR,
        ),
        max_score_queries_per_project_per_hour=min(
            _positive_int(
                payload.get("max_score_queries_per_project_per_hour"), defaults.max_score_queries_per_project_per_hour
            ),
            MAX_SCORE_QUERIES_PER_PROJECT_PER_HOUR,
        ),
        max_score_insights_per_tick=min(
            _positive_int(payload.get("max_score_insights_per_tick"), defaults.max_score_insights_per_tick),
            MAX_SCORE_INSIGHTS_PER_TICK,
        ),
        # A payload from before the split sets only `max_insights_per_tick`, and keeps it as its train cap.
        max_train_insights_per_tick=min(
            _positive_int(
                payload.get("max_train_insights_per_tick"),
                _positive_int(payload.get("max_insights_per_tick"), defaults.max_train_insights_per_tick),
            ),
            MAX_TRAIN_INSIGHTS_PER_TICK,
        ),
        active_window_days=min(
            _positive_int(payload.get("active_window_days"), defaults.active_window_days), MAX_ACTIVE_WINDOW_DAYS
        ),
    )


# A new salt reorders every organization, so change the version only to start a new rollout order.
_ROLLOUT_SALT = "anomaly-scoring-self-driving-v1"
_ROLLOUT_BUCKETS = 10_000


def organization_rollout_bucket(organization_id: "uuid.UUID | str") -> int:
    """The organization's fixed place in the percentage rollout, from 0 to `_ROLLOUT_BUCKETS` - 1."""
    digest = hashlib.sha256(f"{_ROLLOUT_SALT}:{uuid.UUID(str(organization_id))}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % _ROLLOUT_BUCKETS


def in_rollout(config: AnomalyScoringConfig, organization_id: "uuid.UUID | str") -> bool:
    threshold = config.self_driving_organization_percentage * _ROLLOUT_BUCKETS / 100
    return organization_rollout_bucket(organization_id) < threshold


def covers_team(config: AnomalyScoringConfig, team: "Team") -> bool:
    """Whether the tick scores this team's insights. The single-team form of `queue.eligible_teams`.

    The event quota check of `queue.eligible_teams` is left out. The skip list and the denylist win over every
    enrollment. The percentage rollout enrolls only the projects that have an enabled signal source.
    """
    organization_id = str(team.organization_id)
    if not config.enabled or team.id in config.skip_team_ids or organization_id in config.deny_organization_ids:
        return False
    if organization_id in config.organization_ids:
        return not config.allow_team_ids or team.id in config.allow_team_ids
    if not in_rollout(config, organization_id):
        return False
    from products.signals.backend.facade.api import (
        has_enabled_source,  # noqa: PLC0415 — the facade imports this module through `search`
    )

    return has_enabled_source(team.id)


def read_payload() -> dict | None:
    return read_flag_payload(ANOMALY_SCORING_FLAG, ANOMALY_SCORING_FLAG_DISTINCT_ID)


def read_config(payload: Any) -> AnomalyScoringConfig:
    config = parse_config(payload)
    logger.info(
        "anomaly_scoring_config_read",
        enabled=config.enabled,
        organizations=len(config.organization_ids),
        allow_teams=len(config.allow_team_ids),
        self_driving_organization_percentage=config.self_driving_organization_percentage,
        denied_organizations=len(config.deny_organization_ids),
    )
    return config
