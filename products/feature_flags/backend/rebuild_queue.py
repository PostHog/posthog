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

A rebuild calls ``update_flag_definitions_cache``, which rebuilds both variants, so
the ``flags_without_cohorts`` cache is healed as a side effect of a with-cohorts miss.
"""

import time

import redis as redis_lib
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter, Gauge

from posthog.redis import get_client

from products.feature_flags.backend.local_evaluation import flag_definitions_hypercache, update_flag_definitions_cache

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

DRAIN_BATCH_SIZE = 500
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
    "Age of the oldest pending flag-definitions rebuild request",
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

    members = redis.zrange(REBUILD_REQUESTS_ZSET, 0, batch_size - 1)
    for raw in members:
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

        result = "success" if _rebuild_one(redis, team_id) else "failure"
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


def _rebuild_one(redis: redis_lib.Redis, team_id: int) -> bool:
    """Rebuild one team's cache; track the failure streak and trip the circuit."""
    try:
        ok = update_flag_definitions_cache(team_id)
    except SoftTimeLimitExceeded:
        # The drain task hit its soft time limit mid-rebuild. Let it propagate so the
        # task winds down cleanly before the hard limit, and don't count it as a team
        # failure (it would wrongly advance the streak and could trip the circuit).
        raise
    except Exception:
        logger.exception("flag definitions self-heal rebuild raised", team_id=team_id)
        ok = False

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
