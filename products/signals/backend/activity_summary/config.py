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

from products.signals.backend.activity_summary.logic import MIN_UNITS, MIN_UPDATE_INTERVAL
from products.signals.backend.activity_summary.render import DEFAULT_LIMITS, RenderLimits
from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

ACTIVITY_SUMMARY_FLAG = "activity-summary"
# Not a person: the flag must serve its payload to this id.
ACTIVITY_SUMMARY_FLAG_DISTINCT_ID = "signals_activity_summary"


@frozen
class ActivitySummaryConfig:
    enabled: bool = False
    organization_ids: tuple[str, ...] = ()
    skip_team_ids: tuple[int, ...] = ()
    max_pairs_per_tick: int = 50
    # Rolling 24 hours, counted from the stored rows, so the caps hold across ticks and workers.
    max_pairs_per_day: int = 500
    max_cost_usd_per_day: float = 5.0
    max_concurrency: int = 4
    min_units: int = MIN_UNITS
    min_update_interval_hours: float = MIN_UPDATE_INTERVAL.total_seconds() / 3600
    emit_embeddings: bool = True
    capture_events: bool = True
    limits: RenderLimits = DEFAULT_LIMITS
    # Summaries generated before this time are rebuilt from the full window, as after a version change.
    rebuild_before: datetime.datetime | None = None


DISABLED = ActivitySummaryConfig()


def _positive_int(value: Any, default: int) -> int:
    # `bool` is an `int` subclass, and `true` is not a count.
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _positive_number(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return default
    return float(value)


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


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
        organization_ids=_organization_ids(payload.get("organization_ids")),
        skip_team_ids=_team_ids(payload.get("skip_team_ids")),
        max_pairs_per_tick=_positive_int(payload.get("max_pairs_per_tick"), defaults.max_pairs_per_tick),
        max_pairs_per_day=_positive_int(payload.get("max_pairs_per_day"), defaults.max_pairs_per_day),
        max_cost_usd_per_day=_positive_number(payload.get("max_cost_usd_per_day"), defaults.max_cost_usd_per_day),
        max_concurrency=_positive_int(payload.get("max_concurrency"), defaults.max_concurrency),
        min_units=_positive_int(payload.get("min_units"), defaults.min_units),
        min_update_interval_hours=_positive_number(
            payload.get("min_update_interval_hours"), defaults.min_update_interval_hours
        ),
        emit_embeddings=_bool(payload.get("emit_embeddings"), defaults.emit_embeddings),
        capture_events=_bool(payload.get("capture_events"), defaults.capture_events),
        limits=parse_limits(payload.get("limits")),
        rebuild_before=_timestamp(payload.get("rebuild_before")),
    )


def read_config() -> ActivitySummaryConfig:
    config = parse_config(read_flag_payload(ACTIVITY_SUMMARY_FLAG, ACTIVITY_SUMMARY_FLAG_DISTINCT_ID))
    logger.info(
        "activity_summary_config_read",
        enabled=config.enabled,
        organizations=len(config.organization_ids),
    )
    return config
