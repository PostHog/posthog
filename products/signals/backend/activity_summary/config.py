"""The levers of the scheduled activity summary tick, read from the `activity-summary` flag payload.

The parse fails closed: a missing, malformed or unreadable payload turns the tick off. An invalid
field falls back to its default, and no default is unbounded.
"""

import datetime
import dataclasses
from typing import Any

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.activity_summary.logic import (
    MAX_SKIP_BACKOFF,
    MAX_VERSIONS,
    MIN_UNITS,
    MIN_UPDATE_INTERVAL,
    VIEW_UPDATE_INTERVAL,
)
from products.signals.backend.activity_summary.render import DEFAULT_LIMITS, RenderLimits
from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

ACTIVITY_SUMMARY_FLAG = "activity-summary"
# Not a person: the flag must serve its payload to this id.
ACTIVITY_SUMMARY_FLAG_DISTINCT_ID = "signals_activity_summary"
# One unit of a source never adds more than this to the pending score.
MAX_SOURCE_WEIGHT = 10.0


@frozen
class SourceWeights:
    """The pending score that one unit of each queue source adds."""

    # An activity log row that passes the filters of `inputs.user_activity`.
    activity: float = 1.0
    tasks: float = 1.0
    # An object first opened after the pair's watermark: it has no view day on or before the watermark day.
    new_views: float = 0.5
    # A new day of opening an object that the pair also opened on or before the watermark day.
    repeat_view_days: float = 0.0
    # A new day of opening a product scene.
    scene_views: float = 0.0


@frozen
class ActivitySummaryConfig:
    enabled: bool = False
    # Enrolls every organization with AI data processing approval. Otherwise only `organization_ids`.
    enroll_all_approved: bool = False
    organization_ids: tuple[str, ...] = ()
    # Generates for this percentage of the organizations with a project that has an enabled signal source.
    # Only those projects get summaries. A higher percentage keeps the organizations of a lower one.
    self_driving_organization_percentage: float = 0.0
    # The tick never generates for these organizations, even when another field enrolls them.
    deny_organization_ids: tuple[str, ...] = ()
    skip_team_ids: tuple[int, ...] = ()
    max_pairs_per_tick: int = 50
    # Rolling 24 hours, counted from the stored rows, so the caps hold across ticks and workers.
    max_pairs_per_day: int = 500
    max_cost_usd_per_day: float = 5.0
    max_concurrency: int = 4
    min_units: int = MIN_UNITS
    min_update_interval_hours: float = MIN_UPDATE_INTERVAL.total_seconds() / 3600
    max_versions: int = MAX_VERSIONS
    emit_embeddings: bool = True
    capture_events: bool = True
    # Count viewed objects in the queue. When off, the view weights and the view cold start do not apply.
    count_views: bool = False
    source_weights: SourceWeights = SourceWeights()
    # A pair with a current summary is due when its pending score reaches this.
    min_score: float = 3.0
    # The wait after an update that views led, in place of `min_update_interval_hours`.
    view_update_interval_hours: float = VIEW_UPDATE_INTERVAL.total_seconds() / 3600
    # A pair with no summary is due when it opened objects or scenes on this many days in the window.
    cold_start_min_active_days: int = 3
    # The summary age each tier aims for. A pair's staleness is its summary age over this interval.
    target_interval_days_paying: float = 3.0
    target_interval_days_free: float = 5.0
    # A free pair with at least this staleness joins the paying pass, so paying pairs cannot starve it.
    max_overdue_factor: float = 3.0
    # Added to the score of a pair with no summary, because a first summary changes the most.
    cold_start_bonus: float = 5.0
    # The share of the tick that the paying pass can take. The free pass gets the rest.
    paying_budget_share: float = 1.0
    # The largest share of one pass that the pairs of one organization can take.
    max_org_share: float = 0.1
    # The tick stops when this share of its model calls failed or raised.
    max_error_rate: float = 0.5
    max_skip_backoff_hours: float = MAX_SKIP_BACKOFF.total_seconds() / 3600
    limits: RenderLimits = DEFAULT_LIMITS
    # Summaries generated before this time are rebuilt from the full window, as after a version change.
    rebuild_before: datetime.datetime | None = None
    # The largest share of a tick that rebuilds of stale summaries can take. Other updates get the rest.
    rebuild_budget_share: float = 0.3


DISABLED = ActivitySummaryConfig()


def _positive_int(value: Any, default: int) -> int:
    # `bool` is an `int` subclass, and `true` is not a count.
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _positive_number(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return default
    return float(value)


def _fraction(value: Any, default: float) -> float:
    number = _positive_number(value, default)
    return number if number <= 1 else default


def _percentage(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100:
        return default
    return float(value)


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _weight(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= MAX_SOURCE_WEIGHT:
        return default
    return float(value)


def parse_source_weights(payload: Any) -> SourceWeights:
    """The `source_weights` object of the payload. A weight can be zero, so that source adds nothing."""
    defaults = SourceWeights()
    if not isinstance(payload, dict):
        return defaults
    return SourceWeights(
        **{
            field.name: _weight(payload.get(field.name), getattr(defaults, field.name))
            for field in dataclasses.fields(SourceWeights)
        }
    )


def _team_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def _organization_ids(value: Any) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str) and item) if isinstance(value, list) else ()


def parse_limits(payload: Any) -> RenderLimits:
    """The `limits` object of the payload. An invalid field gets its default, a large one its `max_value`."""
    if not isinstance(payload, dict):
        return DEFAULT_LIMITS
    return RenderLimits(
        **{
            field.name: min(
                _positive_int(payload.get(field.name), getattr(DEFAULT_LIMITS, field.name)), field.metadata["max_value"]
            )
            for field in dataclasses.fields(RenderLimits)
        }
    )


def _timestamp(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    # A future time would mark every new summary stale again, so it waits until the time passes.
    return parsed if parsed <= timezone.now() else None


def parse_config(payload: Any) -> ActivitySummaryConfig:
    if not isinstance(payload, dict) or payload.get("enabled") is not True:
        return DISABLED
    defaults = ActivitySummaryConfig()
    return ActivitySummaryConfig(
        enabled=True,
        enroll_all_approved=_bool(payload.get("enroll_all_approved"), defaults.enroll_all_approved),
        organization_ids=_organization_ids(payload.get("organization_ids")),
        self_driving_organization_percentage=_percentage(
            payload.get("self_driving_organization_percentage"), defaults.self_driving_organization_percentage
        ),
        deny_organization_ids=_organization_ids(payload.get("deny_organization_ids")),
        skip_team_ids=_team_ids(payload.get("skip_team_ids")),
        max_pairs_per_tick=_positive_int(payload.get("max_pairs_per_tick"), defaults.max_pairs_per_tick),
        max_pairs_per_day=_positive_int(payload.get("max_pairs_per_day"), defaults.max_pairs_per_day),
        max_cost_usd_per_day=_positive_number(payload.get("max_cost_usd_per_day"), defaults.max_cost_usd_per_day),
        max_concurrency=_positive_int(payload.get("max_concurrency"), defaults.max_concurrency),
        min_units=_positive_int(payload.get("min_units"), defaults.min_units),
        min_update_interval_hours=_positive_number(
            payload.get("min_update_interval_hours"), defaults.min_update_interval_hours
        ),
        max_versions=_positive_int(payload.get("max_versions"), defaults.max_versions),
        emit_embeddings=_bool(payload.get("emit_embeddings"), defaults.emit_embeddings),
        capture_events=_bool(payload.get("capture_events"), defaults.capture_events),
        count_views=_bool(payload.get("count_views"), defaults.count_views),
        source_weights=parse_source_weights(payload.get("source_weights")),
        min_score=_positive_number(payload.get("min_score"), defaults.min_score),
        view_update_interval_hours=_positive_number(
            payload.get("view_update_interval_hours"), defaults.view_update_interval_hours
        ),
        cold_start_min_active_days=_positive_int(
            payload.get("cold_start_min_active_days"), defaults.cold_start_min_active_days
        ),
        target_interval_days_paying=_positive_number(
            payload.get("target_interval_days_paying"), defaults.target_interval_days_paying
        ),
        target_interval_days_free=_positive_number(
            payload.get("target_interval_days_free"), defaults.target_interval_days_free
        ),
        max_overdue_factor=_positive_number(payload.get("max_overdue_factor"), defaults.max_overdue_factor),
        cold_start_bonus=_positive_number(payload.get("cold_start_bonus"), defaults.cold_start_bonus),
        paying_budget_share=_fraction(payload.get("paying_budget_share"), defaults.paying_budget_share),
        max_org_share=_fraction(payload.get("max_org_share"), defaults.max_org_share),
        max_error_rate=_fraction(payload.get("max_error_rate"), defaults.max_error_rate),
        max_skip_backoff_hours=_positive_number(payload.get("max_skip_backoff_hours"), defaults.max_skip_backoff_hours),
        limits=parse_limits(payload.get("limits")),
        rebuild_before=_timestamp(payload.get("rebuild_before")),
        rebuild_budget_share=_fraction(payload.get("rebuild_budget_share"), defaults.rebuild_budget_share),
    )


def read_config() -> ActivitySummaryConfig:
    config = parse_config(read_flag_payload(ACTIVITY_SUMMARY_FLAG, ACTIVITY_SUMMARY_FLAG_DISTINCT_ID))
    logger.info(
        "activity_summary_config_read",
        enabled=config.enabled,
        enroll_all_approved=config.enroll_all_approved,
        organizations=len(config.organization_ids),
        self_driving_organization_percentage=config.self_driving_organization_percentage,
        denied_organizations=len(config.deny_organization_ids),
    )
    return config
