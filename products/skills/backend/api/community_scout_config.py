"""The scout settings a published scout is allowed to travel with.

A catalog entry never creates a `SignalScoutConfig`: the store hands a scout to the Signals
scout-create form, which is where a person reviews the settings and submits them. So this holds the
payload to the few fields that form actually shows — cadence, emit posture and tags — and drops
everything else. `network_access`, `model` and `mcp_gateway_server_ids` grant a scout reach into a
team's data and services, and nothing a contributor publishes should be able to preselect them.

The bounds below are local copies of the ones Signals enforces on its own config, the way
`skills.models` keeps a local copy of the scout name prefix: `products.signals` already depends on
`products.skills`, so the reverse import would be a cycle. They are a shape check for a prefill,
not the authority — Signals validates the settings again when the form is submitted.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from croniter import CroniterError, croniter

# Signals holds a scout's cadence between 30 minutes and 30 days.
MIN_RUN_INTERVAL_MINUTES = 30
MAX_RUN_INTERVAL_MINUTES = 43200
MAX_CRON_SCHEDULE_LENGTH = 100
CRON_FIELD_COUNT = 5
CRON_MIN_GAP_SECONDS = MIN_RUN_INTERVAL_MINUTES * 60
CRON_SAMPLE_OCCURRENCES = 100
MAX_TAGS = 10
MAX_TAG_LENGTH = 50


def _validate_run_interval_minutes(value: Any) -> int | None:
    # bool is an int subclass, and `True` would otherwise pass as a 1-minute cadence.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("scout_config.run_interval_minutes must be an integer")
    if not MIN_RUN_INTERVAL_MINUTES <= value <= MAX_RUN_INTERVAL_MINUTES:
        raise ValueError(
            f"scout_config.run_interval_minutes must be between {MIN_RUN_INTERVAL_MINUTES} "
            f"and {MAX_RUN_INTERVAL_MINUTES}"
        )
    return value


def _validate_run_cron_schedule(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("scout_config.run_cron_schedule must be a string or null")
    schedule = value.strip()
    if not schedule:
        return None
    if len(schedule) > MAX_CRON_SCHEDULE_LENGTH:
        raise ValueError(f"scout_config.run_cron_schedule must be {MAX_CRON_SCHEDULE_LENGTH} characters or fewer")
    if len(schedule.split()) != CRON_FIELD_COUNT or not croniter.is_valid(schedule):
        raise ValueError("scout_config.run_cron_schedule must be a valid five-field cron expression")
    iterator = croniter(schedule, datetime(2026, 1, 1, tzinfo=UTC))
    try:
        occurrences = [iterator.get_next(datetime) for _ in range(CRON_SAMPLE_OCCURRENCES)]
    except CroniterError as error:
        raise ValueError("scout_config.run_cron_schedule must match a real date") from error
    min_gap = min((later - earlier).total_seconds() for earlier, later in zip(occurrences, occurrences[1:]))
    if min_gap < CRON_MIN_GAP_SECONDS:
        raise ValueError(
            f"scout_config.run_cron_schedule must schedule runs at least {MIN_RUN_INTERVAL_MINUTES} minutes apart"
        )
    return schedule


def _validate_emit(value: Any) -> bool | None:
    if not isinstance(value, bool):
        raise ValueError("scout_config.emit must be a boolean")
    return value


def _validate_tags(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        raise ValueError("scout_config.tags must be a list of strings")
    tags = [tag for tag in (tag.strip() for tag in value) if tag]
    if not tags:
        return None
    if len(tags) > MAX_TAGS:
        raise ValueError(f"scout_config.tags must have {MAX_TAGS} tags or fewer")
    if any(len(tag) > MAX_TAG_LENGTH for tag in tags):
        raise ValueError(f"each scout_config tag must be {MAX_TAG_LENGTH} characters or fewer")
    return tags


# Each validator returns the value to keep, or None to leave the field out so the scout-create form
# falls back to its own default.
_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "run_interval_minutes": _validate_run_interval_minutes,
    "run_cron_schedule": _validate_run_cron_schedule,
    "emit": _validate_emit,
    "tags": _validate_tags,
}

SHAREABLE_SCOUT_CONFIG_KEYS = frozenset(_VALIDATORS)


def validate_shareable_scout_config(raw: Any) -> dict[str, Any]:
    """Return the shareable subset of a published scout's settings, or raise ValueError.

    Absent and null both mean "no settings", which is a scout that arrives on the create form's
    defaults. An unknown key is rejected rather than dropped: a contributor who wrote
    `network_access: full` should be told the store will not carry it, not have it silently ignored
    and believe their scout ships with it.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("scout_config must be an object")

    unknown = sorted(set(raw) - SHAREABLE_SCOUT_CONFIG_KEYS)
    if unknown:
        raise ValueError(
            f"scout_config cannot carry {', '.join(unknown)} — only "
            f"{', '.join(sorted(SHAREABLE_SCOUT_CONFIG_KEYS))} travel with a published scout"
        )

    config: dict[str, Any] = {}
    for key, validate in _VALIDATORS.items():
        if key not in raw:
            continue
        value = validate(raw[key])
        if value is not None:
            config[key] = value
    return config
