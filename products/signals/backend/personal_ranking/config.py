"""The levers of the personal inbox ranking, read from the `personal-inbox-ranking` flag payload.

A missing or unreadable payload gives the code defaults. An invalid field falls back to its default,
a large one to its maximum, so no value is unbounded. `"enabled": false` in the payload is the kill
switch: it stops every build. `max_builds_per_day` limits the builds that call the model across every
person in one region.

The optional `pools` list replaces the default candidate pools, in order. Every pool holds only reports
tied to the person, so a personal list never takes reports from across the project. An invalid entry is
dropped and logged. When no entry is valid, the build uses the default pools.

The optional `tick` object holds the levers of the scheduled tick (`tick.py`). Its parse fails closed:
a missing or malformed object, or one without `"enabled": true`, turns the tick off. An enabled tick raises
`freshness_minutes` to its `target_interval_minutes`, and limits `max_tick_builds_per_day` to a share of
`max_builds_per_day`.
"""

import re
from dataclasses import replace
from typing import Any, Literal, cast, get_args

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.scout_harness.team_limits import read_flag_payload

logger = structlog.get_logger(__name__)

PERSONAL_INBOX_RANKING_FLAG = "personal-inbox-ranking"
# Not a person: the flag must serve its payload to this id.
PERSONAL_INBOX_RANKING_FLAG_DISTINCT_ID = "signals_personal_inbox_ranking"
MAX_MODEL_NAME_CHARS = 100
DEFAULT_MODEL = "gpt-6.1-terra"

ReasoningEffort = Literal["minimal", "low", "medium", "high"]
REASONING_EFFORTS: tuple[ReasoningEffort, ...] = get_args(ReasoningEffort)

PoolSource = Literal["for_you_recommended", "for_you_updated", "assigned"]
POOL_SOURCES: tuple[PoolSource, ...] = get_args(PoolSource)
MAX_POOLS = 10
_POOL_NAME = re.compile(r"^[a-z0-9_]{1,40}$")
# The keys a payload pool entry may have. Any other key drops the entry, so a typo shows in the logs.
_POOL_KEYS = frozenset({"source", "size", "name"})


@frozen
class ReasonLimits:
    """The longest reason, in characters, of an entry in each tier."""

    top: int = 140
    worth_a_look: int = 110
    later: int = 80


@frozen
class CandidatePool:
    """One source of candidates. The name labels the pool on each candidate and in the build event."""

    name: str
    source: PoolSource
    # 0 turns the pool off.
    size: int


@frozen
class PersonalRankingTickConfig:
    enabled: bool = False
    # Builds for every project of these organizations.
    organization_ids: tuple[str, ...] = ()
    # Builds for this percentage of the organizations with a project that has an enabled signal source.
    # Only those projects get builds. A higher percentage keeps the organizations of a lower one.
    self_driving_organization_percentage: float = 0.0
    # The tick never builds for these organizations, even when another field enrolls them.
    deny_organization_ids: tuple[str, ...] = ()
    skip_team_ids: tuple[int, ...] = ()
    # A pair is due when its latest list was built or checked longer ago than this.
    target_interval_minutes: int = 60
    # A due pair with no list, or a list older than this, goes first. The payload default is twice the target interval.
    overdue_after_minutes: int = 120
    # Only pairs with activity in this many days are due.
    active_days: int = 7
    max_pairs_per_tick: int = 20
    max_concurrency: int = 4
    # Tick builds that call the model, in one Redis token bucket per region. They also spend `max_builds_per_day`.
    max_tick_builds_per_day: int = 100
    # The largest share of one tick that the pairs of one organization can take.
    max_org_share: float = 0.25
    # The tick stops when this share of its model calls failed or raised.
    max_error_rate: float = 0.5
    # The tick starts no pair after this share of its schedule interval, so the last pairs end before the next tick.
    time_budget_share: float = 0.6


TICK_DISABLED = PersonalRankingTickConfig()
# The rest of the shared limit stays free for `refresh` and `focus` requests, which a person is waiting on.
TICK_SHARE_OF_SHARED_BUILDS = 0.8

_TICK_MAXIMUMS: dict[str, int] = {
    "target_interval_minutes": 1440,
    "active_days": 90,
    "max_pairs_per_tick": 2000,
    "max_concurrency": 100,
    "max_tick_builds_per_day": 50000,
}
_MAX_OVERDUE_AFTER_MINUTES = 2 * _TICK_MAXIMUMS["target_interval_minutes"]
# A larger share lets the pairs started at the end of a tick run into the next tick.
_MAX_TIME_BUDGET_SHARE = 0.85


@frozen
class PersonalRankingConfig:
    enabled: bool = True
    model: str = DEFAULT_MODEL
    reasoning_effort: ReasoningEffort = "low"
    # The `for_you_recommended` pool reads reports created in this window.
    window_days: int = 14
    for_you_recommended_pool: int = 20
    # No window, so older reports with new activity come in too.
    for_you_updated_pool: int = 10
    assigned_pool: int = 10
    # The pools in merge order. Empty uses `default_pools`, which take their sizes from the `*_pool` fields.
    pools: tuple[CandidatePool, ...] = ()
    max_candidates: int = 40
    # The model ranks only this many candidates. The others follow in model order. At most `max_limit`.
    rank_top: int = 25
    # The most entries in each tier. The validator moves an entry past a cap down one tier and keeps its rank.
    top_max: int = 5
    worth_a_look_max: int = 15
    # The entries that get a `next_step`, and the most a caller can ask for.
    default_limit: int = 25
    max_limit: int = 50
    reason_limits: ReasonLimits = ReasonLimits()
    next_step_max_chars: int = 160
    profile_max_chars: int = 1500
    # Names of owned and watched objects from the activity summary, each.
    max_object_names: int = 8
    focus_max_chars: int = 500
    timeout_seconds: float = 90.0
    max_completion_tokens: int = 16000
    # The `for_me` endpoint reuses a stored list this many minutes old or newer while its inputs are the same.
    freshness_minutes: int = 60
    # Builds one person may start from the endpoint: a short burst, an hourly refill and a daily cap.
    build_burst: int = 2
    builds_per_hour: int = 12
    builds_per_day: int = 40
    # Builds that call the model, across every person in one region. Each region has its own Redis, so each counts on its own.
    max_builds_per_day: int = 500
    # Each build keeps this many of the person's newest rows and deletes the older ones.
    max_rows_per_person: int = 5
    tick: PersonalRankingTickConfig = TICK_DISABLED


DEFAULTS = PersonalRankingConfig()

# The largest value each numeric field takes from the payload.
_MAXIMUMS: dict[str, int] = {
    "window_days": 90,
    "for_you_recommended_pool": 100,
    "for_you_updated_pool": 100,
    "assigned_pool": 100,
    "max_candidates": 100,
    "pool_size": 100,
    "rank_top": 100,
    "top_max": 50,
    "worth_a_look_max": 100,
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
    "max_builds_per_day": 50000,
    "max_rows_per_person": 100,
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


def _reasoning_effort(value: Any) -> ReasoningEffort:
    return cast(ReasoningEffort, value) if value in REASONING_EFFORTS else DEFAULTS.reasoning_effort


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


def _fraction(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= 1:
        return default
    return float(value)


def _percentage(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100:
        return TICK_DISABLED.self_driving_organization_percentage
    return float(value)


def _organization_ids(value: Any) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str) and item) if isinstance(value, list) else ()


def _team_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def parse_tick_config(payload: Any) -> PersonalRankingTickConfig:
    if not isinstance(payload, dict) or payload.get("enabled") is not True:
        return TICK_DISABLED
    ints = {
        name: _bounded_int(payload.get(name), getattr(TICK_DISABLED, name), maximum)
        for name, maximum in _TICK_MAXIMUMS.items()
    }
    return PersonalRankingTickConfig(
        enabled=True,
        organization_ids=_organization_ids(payload.get("organization_ids")),
        self_driving_organization_percentage=_percentage(payload.get("self_driving_organization_percentage")),
        deny_organization_ids=_organization_ids(payload.get("deny_organization_ids")),
        skip_team_ids=_team_ids(payload.get("skip_team_ids")),
        max_org_share=_fraction(payload.get("max_org_share"), TICK_DISABLED.max_org_share),
        max_error_rate=_fraction(payload.get("max_error_rate"), TICK_DISABLED.max_error_rate),
        overdue_after_minutes=_bounded_int(
            payload.get("overdue_after_minutes"), 2 * ints["target_interval_minutes"], _MAX_OVERDUE_AFTER_MINUTES
        ),
        time_budget_share=_bounded_number(
            payload.get("time_budget_share"), TICK_DISABLED.time_budget_share, _MAX_TIME_BUDGET_SHARE
        ),
        **ints,
    )


def _fit_tick_to_shared_limit(tick: PersonalRankingTickConfig, max_builds_per_day: int) -> PersonalRankingTickConfig:
    largest = max(int(max_builds_per_day * TICK_SHARE_OF_SHARED_BUILDS), 1)
    return replace(tick, max_tick_builds_per_day=min(tick.max_tick_builds_per_day, largest))


def default_pools(config: PersonalRankingConfig) -> tuple[CandidatePool, ...]:
    return (
        CandidatePool(name="for_you_recommended", source="for_you_recommended", size=config.for_you_recommended_pool),
        CandidatePool(name="for_you_updated", source="for_you_updated", size=config.for_you_updated_pool),
        CandidatePool(name="assigned", source="assigned", size=config.assigned_pool),
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


def _parse_pool(entry: Any) -> CandidatePool:
    if not isinstance(entry, dict):
        raise _InvalidPool("entry must be an object")
    source = entry.get("source")
    if source not in POOL_SOURCES:
        raise _InvalidPool(f"source must be one of {', '.join(POOL_SOURCES)}")
    source = cast(PoolSource, source)
    unknown = set(entry) - _POOL_KEYS
    if unknown:
        raise _InvalidPool(f"unknown keys: {', '.join(sorted(unknown))}")
    name = entry.get("name", source)
    if not isinstance(name, str) or not _POOL_NAME.match(name):
        raise _InvalidPool("name must be 1 to 40 lowercase letters, digits or underscores")
    return CandidatePool(
        name=name,
        source=source,
        size=_pool_count(entry, "size", minimum=0, maximum=_MAXIMUMS["pool_size"]),
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
    tick = parse_tick_config(payload.get("tick"))
    if tick.enabled:
        tick = _fit_tick_to_shared_limit(tick, ints["max_builds_per_day"])
        # A shorter freshness makes a plain read rebuild a list that the tick checked inside its interval.
        ints["freshness_minutes"] = max(ints["freshness_minutes"], tick.target_interval_minutes)
    return PersonalRankingConfig(
        enabled=payload.get("enabled") is not False,
        model=_model(payload.get("model")),
        reasoning_effort=_reasoning_effort(payload.get("reasoning_effort")),
        reason_limits=_reason_limits(payload.get("reason_max_chars")),
        pools=_pools(payload.get("pools")),
        tick=tick,
        timeout_seconds=_bounded_number(
            payload.get("timeout_seconds"), DEFAULTS.timeout_seconds, _MAXIMUMS["timeout_seconds"]
        ),
        max_limit=max_limit,
        **{
            **ints,
            "default_limit": min(ints["default_limit"], max_limit),
            "rank_top": min(ints["rank_top"], max_limit),
        },
    )


def list_limit(config: PersonalRankingConfig, limit: int | None) -> int:
    """The entries a build or a read lists: the caller's `limit`, else `default_limit`, at most `max_limit`."""
    return min(max(limit or config.default_limit, 1), config.max_limit)


def effective_config(config: PersonalRankingConfig) -> dict[str, Any]:
    """The levers that change the speed of a build, so a dogfood run shows which values it used."""
    return {
        "enabled": config.enabled,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "rank_top": config.rank_top,
        "max_candidates": config.max_candidates,
        "timeout_seconds": config.timeout_seconds,
        "max_completion_tokens": config.max_completion_tokens,
    }


def read_config() -> PersonalRankingConfig:
    config = parse_config(read_flag_payload(PERSONAL_INBOX_RANKING_FLAG, PERSONAL_INBOX_RANKING_FLAG_DISTINCT_ID))
    logger.info(
        "personal_inbox_ranking_config_read",
        **effective_config(config),
        pools=[pool.name for pool in candidate_pools(config) if pool.size],
    )
    return config
