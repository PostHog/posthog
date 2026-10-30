"""The levers of the personal inbox ranking, read from the `personal-inbox-ranking` flag payload.

A missing or unreadable payload gives the code defaults. An invalid field falls back to its default,
a large one to its maximum, so no value is unbounded. `"enabled": false` in the payload is the kill
switch: it stops every build.
"""

from typing import Any

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

PERSONAL_INBOX_RANKING_FLAG = "personal-inbox-ranking"
# Not a person: the flag must serve its payload to this id.
PERSONAL_INBOX_RANKING_FLAG_DISTINCT_ID = "signals_personal_inbox_ranking"
MAX_MODEL_NAME_CHARS = 100
DEFAULT_MODEL = "gpt-6-luna"


@frozen
class ReasonLimits:
    """The longest reason, in characters, of an entry in each tier."""

    top: int = 240
    worth_a_look: int = 160
    later: int = 100


@frozen
class PersonalRankingConfig:
    enabled: bool = True
    model: str = DEFAULT_MODEL
    # The `for_you` pool in `sort=recommended` order and the two ranking model pools read reports created in this window.
    window_days: int = 14
    for_you_recommended_pool: int = 30
    # No window, so older reports with new activity come in too.
    for_you_updated_pool: int = 20
    assigned_pool: int = 20
    actionable_pool: int = 20
    new_pool: int = 20
    max_candidates: int = 60
    # The entries that get a `next_step`, and the most a caller can ask for.
    default_limit: int = 25
    max_limit: int = 50
    reason_limits: ReasonLimits = ReasonLimits()
    next_step_max_chars: int = 160
    profile_max_chars: int = 1500
    # Names of owned and watched objects from the activity summary, each.
    max_object_names: int = 8
    focus_max_chars: int = 500
    timeout_seconds: float = 30.0
    max_completion_tokens: int = 8000


DEFAULTS = PersonalRankingConfig()

# The largest value each numeric field takes from the payload.
_MAXIMUMS: dict[str, int] = {
    "window_days": 90,
    "for_you_recommended_pool": 100,
    "for_you_updated_pool": 100,
    "assigned_pool": 100,
    "actionable_pool": 100,
    "new_pool": 100,
    "max_candidates": 100,
    "default_limit": 100,
    "max_limit": 100,
    "next_step_max_chars": 400,
    "profile_max_chars": 4000,
    "max_object_names": 20,
    "focus_max_chars": 2000,
    "timeout_seconds": 120,
    "max_completion_tokens": 16000,
    "reason_max_chars": 500,
}


def _bounded_int(value: Any, default: int, maximum: int) -> int:
    # `bool` is an `int` subclass, and `true` is not a count.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return min(value, maximum)


def _bounded_number(value: Any, default: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return default
    return float(min(value, maximum))


def _model(value: Any) -> str:
    return value if isinstance(value, str) and value.strip() and len(value) <= MAX_MODEL_NAME_CHARS else DEFAULTS.model


def _reason_limits(value: Any) -> ReasonLimits:
    defaults = DEFAULTS.reason_limits
    if not isinstance(value, dict):
        return defaults
    maximum = _MAXIMUMS["reason_max_chars"]
    return ReasonLimits(
        top=_bounded_int(value.get("top"), defaults.top, maximum),
        worth_a_look=_bounded_int(value.get("worth_a_look"), defaults.worth_a_look, maximum),
        later=_bounded_int(value.get("later"), defaults.later, maximum),
    )


def parse_config(payload: Any) -> PersonalRankingConfig:
    if not isinstance(payload, dict):
        return DEFAULTS
    ints = {
        name: _bounded_int(payload.get(name), getattr(DEFAULTS, name), maximum)
        for name, maximum in _MAXIMUMS.items()
        if name not in {"timeout_seconds", "reason_max_chars"}
    }
    max_limit = ints.pop("max_limit")
    return PersonalRankingConfig(
        enabled=payload.get("enabled") is not False,
        model=_model(payload.get("model")),
        reason_limits=_reason_limits(payload.get("reason_max_chars")),
        timeout_seconds=_bounded_number(
            payload.get("timeout_seconds"), DEFAULTS.timeout_seconds, _MAXIMUMS["timeout_seconds"]
        ),
        max_limit=max_limit,
        **{**ints, "default_limit": min(ints["default_limit"], max_limit)},
    )


def read_config() -> PersonalRankingConfig:
    config = parse_config(read_flag_payload(PERSONAL_INBOX_RANKING_FLAG, PERSONAL_INBOX_RANKING_FLAG_DISTINCT_ID))
    logger.info("personal_inbox_ranking_config_read", enabled=config.enabled, model=config.model)
    return config
