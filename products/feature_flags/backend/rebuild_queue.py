"""
Self-heal queue for the flag-definitions HyperCache.

The Rust ``/flags/definitions`` endpoint reads cohort-inclusive flag definitions
straight from HyperCache with no DB fallback, so a missing entry returns 503 until
something rewrites it. On every such miss the Rust service enqueues the team into a
Redis sorted set (see ``rust/feature-flags/src/api/flag_definitions.rs``); this
module drains that set and rebuilds the cache, so a missing entry self-heals within
~1 minute instead of waiting for the hourly verifier or a manual rewarm.

Throttling keeps a permanently-failing team from being rebuilt on a loop:
- a per-team cooldown bounds attempts to one per ``COOLDOWN_SECONDS``, and
- a consecutive-failure circuit breaker stops attempts entirely for
  ``CIRCUIT_OPEN_SECONDS`` once a team fails ``CIRCUIT_OPEN_THRESHOLD`` times.

Both cache variants (with and without cohorts) are rebuilt, so a with-cohorts miss
heals the without-cohorts entry too. The drain exists for the mass-eviction backlog,
so it loads the whole batch in one DB round (like the verifier) rather than per team.
"""

import time

import redis as redis_lib
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter, Gauge

from posthog.models.team import Team
from posthog.redis import get_client

from products.feature_flags.backend.local_evaluation import (
    _skip_write_if_group_mapping_emptied,
    flag_definitions_hypercache,
    flag_definitions_without_cohorts_hypercache,
)

logger = structlog.get_logger(__name__)

# Sorted set the Rust service writes misses to (member = team_id, score = enqueue
# time in epoch MILLIS). MUST match FLAG_DEFINITIONS_REBUILD_REQUESTS_ZSET in the
# Rust service.
REBUILD_REQUESTS_ZSET = "flag_definitions:rebuild_requests"

# Sorted set of teams with an open circuit (member = team_id, score = expiry epoch
# seconds). Doubles as the dead-letter gauge source via ZCARD after pruning.
CIRCUIT_ZSET = "flag_definitions:rebuild_circuit"

COOLDOWN_KEY = "flag_definitions:rebuild_cooldown:{team_id}"
FAILURE_STREAK_KEY = "flag_definitions:rebuild_fails:{team_id}"

# Each team's rebuild does two synchronous set_cache_value writes (Redis + a blocking
# S3 PUT), all sequential within the task's soft time limit. Kept conservative so a
# full drain stays well under that limit; leftover teams re-drain on the next tick.
DRAIN_BATCH_SIZE = 100
COOLDOWN_SECONDS = 300  # at most one rebuild attempt per team per 5 minutes
# Must stay > COOLDOWN_SECONDS * CIRCUIT_OPEN_THRESHOLD, or the streak key expires
# between cooldown windows and the circuit can never trip.
FAILURE_STREAK_TTL = 3600
CIRCUIT_OPEN_THRESHOLD = 5  # consecutive failures before we stop auto-retrying
CIRCUIT_OPEN_SECONDS = 3600  # how long a tripped circuit blocks auto-retry

REBUILD_PROCESSED = Counter(
    "posthog_flag_definitions_rebuild_processed",
    "Flag-definitions self-heal rebuilds drained from the queue",
    labelnames=["result"],  # success | failure | skipped_cooldown | circuit_open
)
REBUILD_QUEUE_DEPTH = Gauge(
    "posthog_flag_definitions_rebuild_queue_depth",
    "Teams currently waiting in the flag-definitions rebuild queue",
)
REBUILD_OLDEST_AGE = Gauge(
    "posthog_flag_definitions_rebuild_oldest_age_seconds",
    # Score refreshes on every re-enqueue, so this is seconds since the oldest queued
    # team's most recent miss, not time-stuck. Read alongside queue_depth.
    "Seconds since the oldest queued team's most recent miss (read with queue_depth)",
)
REBUILD_DEAD_LETTER = Gauge(
    "posthog_flag_definitions_rebuild_dead_letter_teams",
    "Teams whose rebuild circuit is open (repeatedly failing)",
)


def _parse_team_id(raw: bytes | str) -> int | None:
    """Members are written by Rust as the stringified team id; tolerate bytes/str."""
    try:
        return int(raw.decode() if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError):
        return None


def _redis() -> redis_lib.Redis:
    # Derive from the HyperCache itself, not a standalone constant, so the queue can
    # never read a different Redis than the cache it heals.
    return get_client(flag_definitions_hypercache.redis_url)


def drain_rebuild_requests(batch_size: int = DRAIN_BATCH_SIZE) -> dict[str, int]:
    """Drain the rebuild request set and rebuild each team's cache once.

    Returns a per-result count dict (also useful for tests).
    """
    redis = _redis()
    now = time.time()

    # Prune expired circuits first, then publish gauges for the dashboard.
    redis.zremrangebyscore(CIRCUIT_ZSET, "-inf", now)
    REBUILD_DEAD_LETTER.set(redis.zcard(CIRCUIT_ZSET))
    _emit_queue_gauges(redis, now)

    stats = {"success": 0, "failure": 0, "skipped_cooldown": 0, "circuit_open": 0}

    eligible: list[int] = []
    for raw in redis.zrange(REBUILD_REQUESTS_ZSET, 0, batch_size - 1):
        # Remove first: a still-missing team is re-enqueued by its next miss, so we
        # never drop a genuinely-needed rebuild, but we also don't spin on one entry.
        redis.zrem(REBUILD_REQUESTS_ZSET, raw)

        team_id = _parse_team_id(raw)
        if team_id is None:
            continue

        if redis.zscore(CIRCUIT_ZSET, str(team_id)) is not None:
            stats["circuit_open"] += 1
            REBUILD_PROCESSED.labels(result="circuit_open").inc()
            continue

        # Cooldown bounds attempts even while the team keeps polling and re-enqueuing.
        if not redis.set(COOLDOWN_KEY.format(team_id=team_id), 1, nx=True, ex=COOLDOWN_SECONDS):
            stats["skipped_cooldown"] += 1
            REBUILD_PROCESSED.labels(result="skipped_cooldown").inc()
            continue

        eligible.append(team_id)

    try:
        results = _rebuild_batch(redis, eligible)
    except SoftTimeLimitExceeded:
        # Winding down mid-batch. The cooldown was set up front (it doubles as a mutex
        # against overlapping drains), so un-rebuilt teams would otherwise wait out the
        # full 5-minute cooldown. Release the whole batch's cooldowns so the next drain
        # retries them in ~1 minute; already-rebuilt teams won't re-enqueue, so clearing
        # theirs too is harmless.
        for team_id in eligible:
            redis.delete(COOLDOWN_KEY.format(team_id=team_id))
        raise

    for ok in results.values():
        result = "success" if ok else "failure"
        stats[result] += 1
        REBUILD_PROCESSED.labels(result=result).inc()

    return stats


def _emit_queue_gauges(redis: redis_lib.Redis, now: float) -> None:
    REBUILD_QUEUE_DEPTH.set(redis.zcard(REBUILD_REQUESTS_ZSET))
    oldest = redis.zrange(REBUILD_REQUESTS_ZSET, 0, 0, withscores=True)
    if oldest:
        # score is the most-recent enqueue time in epoch millis. Rust re-enqueues with
        # zadd (not NX), so a team polled every ~30s keeps its score refreshed: this is
        # "time since last miss", bounded by the SDK poll interval, not "time since first
        # miss". A small value is not proof the queue is healthy — read it with depth.
        _, score_ms = oldest[0]
        REBUILD_OLDEST_AGE.set(max(0.0, now - float(score_ms) / 1000.0))
    else:
        REBUILD_OLDEST_AGE.set(0)


def _rebuild_batch(redis: redis_lib.Redis, team_ids: list[int]) -> dict[int, bool]:
    """Rebuild every eligible team from a single batched DB load, then record each
    outcome. Mirrors the verifier: one batch_load_fn per variant, then set_cache_value
    per team (no per-team load_fn), which is the point of draining in one pass.

    A SoftTimeLimitExceeded propagates so the task winds down cleanly (the interrupted
    teams stay missing and are re-enqueued by their next miss). Any other load error
    fails the whole batch — a persistent outage still trips circuits after the usual
    consecutive-failure threshold rather than hammering the DB.
    """
    if not team_ids:
        return {}

    # Both flag_definitions caches are always constructed with a batch_load_fn; bind it
    # to narrow the Optional type and fail loudly if that invariant ever breaks.
    with_cohorts_load = flag_definitions_hypercache.batch_load_fn
    without_cohorts_load = flag_definitions_without_cohorts_hypercache.batch_load_fn
    if with_cohorts_load is None or without_cohorts_load is None:
        raise RuntimeError("flag_definitions hypercaches must be configured with a batch_load_fn")

    try:
        teams = list(Team.objects.filter(id__in=team_ids))
        teams_by_id = {team.id: team for team in teams}
        with_cohorts = with_cohorts_load(teams)
        without_cohorts = without_cohorts_load(teams)
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("flag definitions self-heal batch load failed", team_count=len(team_ids))
        return {team_id: _record_result(redis, team_id, ok=False) for team_id in team_ids}

    results: dict[int, bool] = {}
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            results[team_id] = _record_result(redis, team_id, ok=False)
            continue
        payload = with_cohorts[team_id]
        if _skip_write_if_group_mapping_emptied(team, payload):
            # personhog lag would cache an emptied group_type_mapping; skip both writes
            # without counting a failure (that would wrongly advance the circuit breaker).
            # Release the cooldown so the team retries on the next drain once the mapping
            # is available, rather than staying missing for the full cooldown window.
            redis.delete(COOLDOWN_KEY.format(team_id=team_id))
            continue
        try:
            flag_definitions_hypercache.set_cache_value(team, payload)
            flag_definitions_without_cohorts_hypercache.set_cache_value(team, without_cohorts[team_id])
            ok = True
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.exception("flag definitions self-heal rebuild failed", team_id=team_id)
            ok = False
        results[team_id] = _record_result(redis, team_id, ok=ok)
    return results


def _record_result(redis: redis_lib.Redis, team_id: int, *, ok: bool) -> bool:
    """Track the failure streak and trip/clear the circuit for one team."""
    streak_key = FAILURE_STREAK_KEY.format(team_id=team_id)
    if ok:
        redis.delete(streak_key)
        redis.zrem(CIRCUIT_ZSET, str(team_id))
        return True

    streak = redis.incr(streak_key)
    redis.expire(streak_key, FAILURE_STREAK_TTL)
    if streak >= CIRCUIT_OPEN_THRESHOLD:
        redis.zadd(CIRCUIT_ZSET, {str(team_id): time.time() + CIRCUIT_OPEN_SECONDS})
        logger.warning(
            "flag definitions self-heal circuit opened",
            team_id=team_id,
            streak=streak,
        )
    return False
