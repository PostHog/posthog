"""Atomic enqueue-slot claims for on-demand scans.

The in-flight caps count ReplayObservation rows, but a row only appears once the apply workflow's
first activity runs — so between `start_workflow` and that insert an enqueued scan is invisible to
every counter, and concurrent requests can race past the caps off the same free-looking snapshot.
A claim closes that window: it is taken atomically (single Lua eval, same shape as
posthog/clickhouse/client/limit.py) BEFORE the workflow starts and released once the observation
row exists, so effective headroom is cap minus rows minus live claims and racing requests
serialize on the claim instead of the stale row count.

Fail-open by design: the caps are cost/backpressure guardrails, not billing (the create activity's
quota gate handles spend), so a Redis outage degrades to today's snapshot behavior rather than
blocking scans. Claims are scored with a TTL as the crash net — a claim whose workflow died before
the row insert frees itself when the score expires. If enqueue-to-insert lag ever exceeds the TTL
(severe worker backlog), expired claims free slots early and the cap degrades to snapshot behavior
for the excess.
"""

import time
from uuid import UUID

import structlog

from posthog import redis

from products.replay_vision.backend.temporal.constants import (
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
)

logger = structlog.get_logger(__name__)

# Must exceed worst-case enqueue-to-first-activity lag (queue backlog included); crashed claims
# are reclaimed after this long.
_CLAIM_TTL_SECONDS = 15 * 60

_TEAM_KEY_PREFIX = "@posthog/replay-vision/enqueued-team"
_SCANNER_KEY_PREFIX = "@posthog/replay-vision/enqueued-scanner"

# Evict expired claims, then admit only if BOTH the team and scanner pools have room for a new
# member. Re-claiming an existing member (same deterministic workflow id) never consumes a new
# slot — it only refreshes the expiry, so retries and duplicate requests can't double-count.
_CLAIM_LUA = """
local team_key = KEYS[1]
local scanner_key = KEYS[2]
local now = tonumber(ARGV[1])
local member = ARGV[2]
local team_allowance = tonumber(ARGV[3])
local scanner_allowance = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', team_key, '-inf', now)
redis.call('ZREMRANGEBYSCORE', scanner_key, '-inf', now)

if not redis.call('ZSCORE', team_key, member) then
    if redis.call('ZCARD', team_key) >= team_allowance then
        return 0
    end
    if redis.call('ZCARD', scanner_key) >= scanner_allowance then
        return 0
    end
end

local expiry = now + ttl
redis.call('ZADD', team_key, expiry, member)
redis.call('ZADD', scanner_key, expiry, member)
redis.call('EXPIRE', team_key, ttl)
redis.call('EXPIRE', scanner_key, ttl)
return 1
"""


def _team_key(team_id: int) -> str:
    return f"{_TEAM_KEY_PREFIX}:{team_id}"


def _scanner_key(scanner_id: UUID) -> str:
    return f"{_SCANNER_KEY_PREFIX}:{scanner_id}"


def try_claim_enqueue_slot(
    *,
    team_id: int,
    scanner_id: UUID,
    workflow_id: str,
    team_in_flight_rows: int,
    scanner_in_flight_rows: int,
) -> bool:
    """Atomically claim one enqueue slot against both in-flight caps; True when the scan may start.

    The row counts are the caller's snapshot of persisted in-flight observations; the claim pools
    cover only the not-yet-persisted gap, so each pool's allowance is cap minus rows.
    """
    team_allowance = MAX_IN_FLIGHT_APPLIES_PER_TEAM - team_in_flight_rows
    scanner_allowance = MAX_IN_FLIGHT_APPLIES_PER_SCANNER - scanner_in_flight_rows
    try:
        client = redis.get_client()
        allowed = client.eval(
            _CLAIM_LUA,
            2,
            _team_key(team_id),
            _scanner_key(scanner_id),
            time.time(),
            workflow_id,
            team_allowance,
            scanner_allowance,
            _CLAIM_TTL_SECONDS,
        )
        return bool(allowed)
    except Exception:
        # The caps are backstops, not billing — never block scans on Redis trouble.
        logger.warning("replay_vision.enqueue_claim.failed_open", team_id=team_id, exc_info=True)
        return True


def release_enqueue_claim(*, team_id: int, scanner_id: UUID, workflow_id: str) -> None:
    """Free a claim once its observation row exists (or the start failed). Fail-soft: an unreleased
    claim self-expires via its TTL score."""
    try:
        client = redis.get_client()
        pipeline = client.pipeline()
        pipeline.zrem(_team_key(team_id), workflow_id)
        pipeline.zrem(_scanner_key(scanner_id), workflow_id)
        pipeline.execute()
    except Exception:
        logger.warning("replay_vision.enqueue_claim.release_failed", team_id=team_id, exc_info=True)


def pending_enqueue_claims_for_team(team_id: int) -> int:
    """Live (unexpired) claims for scans enqueued but not yet persisted, for headroom displays."""
    return _pending(_team_key(team_id))


def pending_enqueue_claims_for_scanner(scanner_id: UUID) -> int:
    return _pending(_scanner_key(scanner_id))


def _pending(key: str) -> int:
    try:
        return int(redis.get_client().zcount(key, f"({time.time()}", "+inf"))
    except Exception:
        logger.warning("replay_vision.enqueue_claim.count_failed", key=key, exc_info=True)
        return 0
