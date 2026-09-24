"""
Self-heal queue for the flag-definitions HyperCache.

The Rust ``/flags/definitions`` endpoint reads cohort-inclusive flag definitions
straight from HyperCache with no DB fallback. Two states put a team in this queue
(see ``rust/feature-flags/src/api/flag_definitions.rs``):

- Nothing holds the entry, so the request returns 503 until something rewrites it.
- Redis lost the entry and S3 still has it, so the request succeeds but carries no
  ETag, and the SDK re-downloads the payload on every poll.

This module drains the set and rebuilds the cache, so either state self-heals within
~1 minute instead of waiting for the hourly verifier or a manual rewarm. The rebuild
writes the payload and the ETag together and re-stamps expiry tracking, which returns
the team to the normal refresh cycle.

Throttling keeps a permanently-failing team from being rebuilt on a loop:
- a per-team cooldown bounds attempts to one per ``COOLDOWN_SECONDS``, and
- a consecutive-failure circuit breaker stops attempts entirely for
  ``CIRCUIT_OPEN_SECONDS`` once a team fails ``CIRCUIT_OPEN_THRESHOLD`` times.

The drain exists for the mass-eviction backlog, so it loads the whole batch in one
DB round (like the verifier) rather than per team.
"""

import time

from django.conf import settings

import redis as redis_lib
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter, Gauge
from redis.exceptions import WatchError

from posthog.models.team import Team
from posthog.redis import get_client

from products.feature_flags.backend.local_evaluation import (
    _skip_write_if_group_mapping_emptied,
    flag_definitions_hypercache,
)

logger = structlog.get_logger(__name__)

# Sorted set the Rust service writes rebuild requests to (member = team_id, score =
# epoch MILLIS). The Rust side writes it with ZADD NX, so the score stays at the first
# request and repeated polls cannot reorder the queue or reset the age gauge. MUST match
# FLAG_DEFINITIONS_REBUILD_REQUESTS_ZSET in the Rust service.
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
    "Teams queued or rebuilding in the flag-definitions rebuild queue",
)
REBUILD_OLDEST_AGE = Gauge(
    "posthog_flag_definitions_rebuild_oldest_age_seconds",
    # The NX write keeps a team's first score, so this measures how long a request has
    # waited rather than how often the team polls. A drained team that is still broken
    # re-enters the queue with a new score.
    "Seconds since the oldest queued rebuild request was made",
)
REBUILD_DEAD_LETTER = Gauge(
    "posthog_flag_definitions_rebuild_dead_letter_teams",
    "Teams whose rebuild circuit is open (repeatedly failing)",
)
# Every other gauge here reads the cluster the drain resolved, so a producer and consumer
# split reads as zero on all of them while the enqueue counter still reports ok: a dead
# queue looks healthy. This reads the cluster the drain does not use, which is non-zero
# only while the two ends disagree. Remove it when the dedicated-Redis move is complete.
REBUILD_UNREAD_CLUSTER_DEPTH = Gauge(
    "posthog_flag_definitions_rebuild_unread_cluster_depth",
    "Teams queued on the Redis cluster the drain does not read (0 when both ends agree)",
)


def _parse_team_id(raw: bytes | str) -> int | None:
    """Members are written by Rust as the stringified team id; tolerate bytes/str."""
    try:
        return int(raw.decode() if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError):
        return None


def _redis() -> redis_lib.Redis:
    # Derived from the hypercache, so the consumer follows the same cluster as the
    # writer: dedicated when FLAGS_REDIS_URL registers the alias, shared otherwise.
    # The Rust producer resolves the same setting (`State::flags_namespace_redis_client`),
    # but falls back to the shared cluster when it cannot reach the dedicated one at
    # startup. Such a process enqueues where nothing drains, and its teams wait for the
    # hourly verifier.
    return get_client(flag_definitions_hypercache.redis_url)


def _discard_unless_rebuilding(redis: redis_lib.Redis, cooldown_key: str, member: bytes | str) -> None:
    # The cooldown can change while another drain finishes, so check and remove atomically.
    try:
        with redis.pipeline() as pipe:
            pipe.watch(cooldown_key)
            if pipe.get(cooldown_key) == b"inflight":
                return
            pipe.multi()
            pipe.zrem(REBUILD_REQUESTS_ZSET, member)
            pipe.execute()
    except WatchError:
        # Leave the member for the owner or the next drain after a concurrent change.
        return


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
        team_id = _parse_team_id(raw)
        if team_id is None:
            redis.zrem(REBUILD_REQUESTS_ZSET, raw)
            continue

        cooldown_key = COOLDOWN_KEY.format(team_id=team_id)
        if redis.zscore(CIRCUIT_ZSET, str(team_id)) is not None:
            _discard_unless_rebuilding(redis, cooldown_key, raw)
            stats["circuit_open"] += 1
            REBUILD_PROCESSED.labels(result="circuit_open").inc()
            continue

        # Keep the member while rebuilding so SDK polls cannot enqueue it again.
        if not redis.set(cooldown_key, "inflight", nx=True, ex=COOLDOWN_SECONDS):
            _discard_unless_rebuilding(redis, cooldown_key, raw)
            stats["skipped_cooldown"] += 1
            REBUILD_PROCESSED.labels(result="skipped_cooldown").inc()
            continue

        eligible.append(team_id)

    results: dict[int, bool] = {}
    timed_out = False
    try:
        results = _rebuild_batch(redis, eligible)
    except SoftTimeLimitExceeded:
        timed_out = True
        raise
    finally:
        for team_id in eligible:
            cooldown_key = COOLDOWN_KEY.format(team_id=team_id)
            with redis.pipeline() as pipe:
                pipe.zrem(REBUILD_REQUESTS_ZSET, str(team_id))
                if timed_out or team_id not in results:
                    pipe.delete(cooldown_key)
                else:
                    pipe.set(cooldown_key, "cooldown", xx=True, keepttl=True)
                pipe.execute()

    for ok in results.values():
        result = "success" if ok else "failure"
        stats[result] += 1
        REBUILD_PROCESSED.labels(result=result).inc()

    return stats


def _emit_unread_cluster_gauge() -> None:
    """Publish the queue depth on the cluster the drain does not read, so the deploy window
    and the cleanup step afterwards are both observable. Failures here must not fail a drain,
    because this gauge is diagnostic."""
    if flag_definitions_hypercache.redis_url == settings.REDIS_URL:
        REBUILD_UNREAD_CLUSTER_DEPTH.set(0)
        return
    try:
        depth = get_client(settings.REDIS_URL).zcard(REBUILD_REQUESTS_ZSET)
    except Exception:
        logger.exception("flag definitions self-heal unread cluster gauge failed")
        return
    REBUILD_UNREAD_CLUSTER_DEPTH.set(depth)


def _emit_queue_gauges(redis: redis_lib.Redis, now: float) -> None:
    REBUILD_QUEUE_DEPTH.set(redis.zcard(REBUILD_REQUESTS_ZSET))
    _emit_unread_cluster_gauge()
    oldest = redis.zrange(REBUILD_REQUESTS_ZSET, 0, 0, withscores=True)
    if oldest:
        _, score_ms = oldest[0]
        REBUILD_OLDEST_AGE.set(max(0.0, now - float(score_ms) / 1000.0))
    else:
        REBUILD_OLDEST_AGE.set(0)


def _rebuild_batch(redis: redis_lib.Redis, team_ids: list[int]) -> dict[int, bool]:
    """Rebuild every eligible team from a single batched DB load, then record each
    outcome. Mirrors the verifier: one batch_load_fn, then set_cache_value per team
    (no per-team load_fn), which is the point of draining in one pass.

    A SoftTimeLimitExceeded propagates so the task winds down cleanly (the interrupted
    teams stay missing and are re-enqueued by their next miss). Any other load error
    fails the whole batch — a persistent outage still trips circuits after the usual
    consecutive-failure threshold rather than hammering the DB.
    """
    if not team_ids:
        return {}

    # flag_definitions_hypercache is always constructed with a batch_load_fn; bind it
    # to narrow the Optional type and fail loudly if that invariant ever breaks.
    batch_load = flag_definitions_hypercache.batch_load_fn
    if batch_load is None:
        raise RuntimeError("flag_definitions_hypercache must be configured with a batch_load_fn")

    try:
        teams = list(Team.objects.filter(id__in=team_ids))
        teams_by_id = {team.id: team for team in teams}
        payloads = batch_load(teams)
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
        payload = payloads[team_id]
        if _skip_write_if_group_mapping_emptied(team, payload):
            # personhog lag would cache an emptied group_type_mapping; skip the write
            # without counting a failure (that would wrongly advance the circuit breaker).
            # Omit the result so the drain releases the cooldown for the next poll.
            continue
        try:
            flag_definitions_hypercache.set_cache_value(team, payload)
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
