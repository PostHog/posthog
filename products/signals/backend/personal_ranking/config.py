"""The levers of the personal inbox ranking, read from the `personal-inbox-ranking` flag payload.

A missing or unreadable payload gives the code defaults. An invalid field falls back to its default,
a large one to its maximum, so no value is unbounded. `"enabled": false` in the payload is the kill
switch: it stops every build.

The optional `pools` list replaces the default candidate pools, in order. An invalid entry is dropped
and logged. When no entry is valid, the build uses the default pools.
"""

import re
from typing import Any, Literal, cast, get_args

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

PERSONAL_INBOX_RANKING_FLAG = "personal-inbox-ranking"
# Not a person: the flag must serve its payload to this id.
PERSONAL_INBOX_RANKING_FLAG_DISTINCT_ID = "signals_personal_inbox_ranking"
MAX_MODEL_NAME_CHARS = 100
DEFAULT_MODEL = "gpt-6-luna"

PoolSource = Literal["for_you_recommended", "for_you_updated", "assigned", "scored", "priority"]
POOL_SOURCES: tuple[PoolSource, ...] = get_args(PoolSource)
ScoreHead = Literal["open", "action", "fixed"]
SCORE_HEADS: tuple[ScoreHead, ...] = get_args(ScoreHead)
PriorityLevel = Literal["P0", "P1", "P2", "P3", "P4"]
PRIORITY_LEVELS: tuple[PriorityLevel, ...] = get_args(PriorityLevel)
DEFAULT_LOWEST_PRIORITY: PriorityLevel = "P1"
MAX_POOLS = 10
_POOL_NAME = re.compile(r"^[a-z0-9_]{1,40}$")
# The keys a payload pool entry may have for each source. Any other key drops the entry, so a typo shows in the logs.
_COMMON_POOL_KEYS = frozenset({"source", "size", "name"})
_FILTER_POOL_KEYS = frozenset({"actionable_only", "has_pr", "window_days"})
_POOL_KEYS: dict[PoolSource, frozenset[str]] = {
    "for_you_recommended": _COMMON_POOL_KEYS,
    "for_you_updated": _COMMON_POOL_KEYS,
    "assigned": _COMMON_POOL_KEYS,
    "scored": _COMMON_POOL_KEYS | _FILTER_POOL_KEYS | {"head"},
    "priority": _COMMON_POOL_KEYS | _FILTER_POOL_KEYS | {"lowest_priority"},
}


@frozen
class ReasonLimits:
    """The longest reason, in characters, of an entry in each tier."""

    top: int = 240
    worth_a_look: int = 160
    later: int = 100


@frozen
class CandidatePool:
    """One source of candidates. The name labels the pool on each candidate and in the build event."""

    name: str
    source: PoolSource
    # 0 turns the pool off.
    size: int
    # `scored` only: the ranking model head that orders the pool.
    head: ScoreHead | None = None
    # `priority` only: the pool takes reports with this priority or a more urgent one.
    lowest_priority: PriorityLevel = DEFAULT_LOWEST_PRIORITY
    # `scored` and `priority` only. True takes ready reports judged immediately actionable. False takes
    # ready and pending input reports that are not judged not actionable.
    actionable_only: bool = False
    # `scored` and `priority` only. None takes reports with and without an implementation PR.
    has_pr: bool | None = None
    # `scored` and `priority` only: the days back the pool reads by creation time. None uses the config `window_days`.
    window_days: int | None = None


@frozen
class PersonalRankingConfig:
    enabled: bool = True
    model: str = DEFAULT_MODEL
    # The `for_you_recommended` pool, and the `scored` and `priority` pools without their own `window_days`, read
    # reports created in this window.
    window_days: int = 14
    for_you_recommended_pool: int = 30
    # No window, so older reports with new activity come in too.
    for_you_updated_pool: int = 20
    assigned_pool: int = 20
    actionable_pool: int = 20
    new_pool: int = 20
    # The pools in merge order. Empty uses `default_pools`, which take their sizes from the `*_pool` fields.
    pools: tuple[CandidatePool, ...] = ()
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
    # The `for_me` endpoint reuses a stored list this many minutes old or newer while its inputs are the same.
    freshness_minutes: int = 60
    # Builds one person may start from the endpoint: a short burst, an hourly refill and a daily cap.
    build_burst: int = 2
    builds_per_hour: int = 12
    builds_per_day: int = 40


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
    "pool_size": 100,
    "default_limit": 100,
    "max_limit": 100,
    "next_step_max_chars": 400,
    "profile_max_chars": 4000,
    "max_object_names": 20,
    "focus_max_chars": 2000,
    "timeout_seconds": 120,
    "max_completion_tokens": 16000,
    "freshness_minutes": 1440,
    "build_burst": 20,
    "builds_per_hour": 120,
    "builds_per_day": 500,
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


def default_pools(config: PersonalRankingConfig) -> tuple[CandidatePool, ...]:
    return (
        CandidatePool(name="for_you_recommended", source="for_you_recommended", size=config.for_you_recommended_pool),
        CandidatePool(name="for_you_updated", source="for_you_updated", size=config.for_you_updated_pool),
        CandidatePool(name="assigned", source="assigned", size=config.assigned_pool),
        CandidatePool(
            name="actionable",
            source="scored",
            size=config.actionable_pool,
            head="action",
            actionable_only=True,
            has_pr=False,
        ),
        CandidatePool(name="new", source="scored", size=config.new_pool, head="open"),
    )


def candidate_pools(config: PersonalRankingConfig) -> tuple[CandidatePool, ...]:
    return config.pools or default_pools(config)


class _InvalidPool(ValueError):
    pass


def _pool_count(entry: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _InvalidPool(f"{key} must be an integer of at least {minimum}")
    return min(value, maximum)


def _pool_flag(entry: dict[str, Any], key: str) -> bool | None:
    value = entry.get(key)
    if value is not None and not isinstance(value, bool):
        raise _InvalidPool(f"{key} must be true, false or null")
    return value


def _parse_pool(entry: Any) -> CandidatePool:
    if not isinstance(entry, dict):
        raise _InvalidPool("entry must be an object")
    source = entry.get("source")
    if source not in POOL_SOURCES:
        raise _InvalidPool(f"source must be one of {', '.join(POOL_SOURCES)}")
    source = cast(PoolSource, source)
    unknown = set(entry) - _POOL_KEYS[source]
    if unknown:
        raise _InvalidPool(f"unknown keys for source {source}: {', '.join(sorted(unknown))}")
    head = entry.get("head")
    if source == "scored" and head not in SCORE_HEADS:
        raise _InvalidPool(f"head must be one of {', '.join(SCORE_HEADS)}")
    lowest_priority = entry.get("lowest_priority", DEFAULT_LOWEST_PRIORITY)
    if lowest_priority not in PRIORITY_LEVELS:
        raise _InvalidPool(f"lowest_priority must be one of {', '.join(PRIORITY_LEVELS)}")
    default_name = f"scored_{head}" if source == "scored" else source
    name = entry.get("name", default_name)
    if not isinstance(name, str) or not _POOL_NAME.match(name):
        raise _InvalidPool("name must be 1 to 40 lowercase letters, digits or underscores")
    return CandidatePool(
        name=name,
        source=source,
        size=_pool_count(entry, "size", minimum=0, maximum=_MAXIMUMS["pool_size"]),
        head=cast(ScoreHead, head) if source == "scored" else None,
        lowest_priority=cast(PriorityLevel, lowest_priority),
        actionable_only=_pool_flag(entry, "actionable_only") or False,
        has_pr=_pool_flag(entry, "has_pr"),
        window_days=None
        if entry.get("window_days") is None
        else _pool_count(entry, "window_days", minimum=1, maximum=_MAXIMUMS["window_days"]),
    )


def _pools(value: Any) -> tuple[CandidatePool, ...]:
    """The valid entries of the payload `pools` list. Empty when the list is missing or holds no valid entry."""
    if value is None:
        return ()
    if not isinstance(value, list):
        logger.warning("personal_inbox_ranking_pools_invalid", reason="pools must be a list")
        return ()
    pools: list[CandidatePool] = []
    for index, entry in enumerate(value):
        try:
            if index >= MAX_POOLS:
                raise _InvalidPool(f"at most {MAX_POOLS} pools")
            pool = _parse_pool(entry)
            if any(existing.name == pool.name for existing in pools):
                raise _InvalidPool(f"duplicate name {pool.name}")
        except _InvalidPool as error:
            logger.warning("personal_inbox_ranking_pool_dropped", index=index, reason=str(error))
            continue
        pools.append(pool)
    if not pools:
        logger.warning("personal_inbox_ranking_pools_invalid", reason="no valid pool, so the default pools apply")
    return tuple(pools)


def parse_config(payload: Any) -> PersonalRankingConfig:
    if not isinstance(payload, dict):
        return DEFAULTS
    ints = {
        name: _bounded_int(payload.get(name), getattr(DEFAULTS, name), maximum)
        for name, maximum in _MAXIMUMS.items()
        if name not in {"timeout_seconds", "reason_max_chars", "pool_size"}
    }
    max_limit = ints.pop("max_limit")
    return PersonalRankingConfig(
        enabled=payload.get("enabled") is not False,
        model=_model(payload.get("model")),
        reason_limits=_reason_limits(payload.get("reason_max_chars")),
        pools=_pools(payload.get("pools")),
        timeout_seconds=_bounded_number(
            payload.get("timeout_seconds"), DEFAULTS.timeout_seconds, _MAXIMUMS["timeout_seconds"]
        ),
        max_limit=max_limit,
        **{**ints, "default_limit": min(ints["default_limit"], max_limit)},
    )


def read_config() -> PersonalRankingConfig:
    config = parse_config(read_flag_payload(PERSONAL_INBOX_RANKING_FLAG, PERSONAL_INBOX_RANKING_FLAG_DISTINCT_ID))
    logger.info(
        "personal_inbox_ranking_config_read",
        enabled=config.enabled,
        model=config.model,
        pools=[pool.name for pool in candidate_pools(config) if pool.size],
    )
    return config
