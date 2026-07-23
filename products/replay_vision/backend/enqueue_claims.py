"""Atomic enqueue-slot claims for on-demand scans.

The in-flight caps count ReplayObservation rows, but a row only appears once the apply workflow's
first activity runs, so concurrent requests can race past the caps in that gap. A claim is taken
atomically (single Lua eval, same shape as posthog/clickhouse/client/limit.py) before the workflow
starts and released once the row exists; the TTL score reclaims claims from crashed workflows.
Fail-open: the caps are backpressure guardrails, not billing, so Redis trouble degrades to the
snapshot behavior instead of blocking scans.
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

# Must exceed worst-case enqueue-to-first-activity lag; crashed claims are reclaimed after this long.
_CLAIM_TTL_SECONDS = 15 * 60

_TEAM_KEY_PREFIX = "@posthog/replay-vision/enqueued-team"
_SCANNER_KEY_PREFIX = "@posthog/replay-vision/enqueued-scanner"

# Re-claiming an existing member (same deterministic workflow id) only refreshes its expiry, so
# duplicate requests and retries never consume a second slot.
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

    The claim pools cover only the not-yet-persisted gap, so each pool's allowance is its cap minus
    the caller's snapshot of persisted in-flight rows.
    """
    team_allowance = MAX_IN_FLIGHT_APPLIES_PER_TEAM - team_in_flight_rows
    scanner_allowance = MAX_IN_FLIGHT_APPLIES_PER_SCANNER - scanner_in_flight_rows
    try:
        allowed = redis.get_client().eval(
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
        logger.warning("replay_vision.enqueue_claim.failed_open", team_id=team_id, exc_info=True)
        return True


def release_enqueue_claim(*, team_id: int, scanner_id: UUID, workflow_id: str) -> None:
    """Free a claim once its observation row exists (or the start failed); unreleased claims self-expire."""
    try:
        pipeline = redis.get_client().pipeline()
        pipeline.zrem(_team_key(team_id), workflow_id)
        pipeline.zrem(_scanner_key(scanner_id), workflow_id)
        pipeline.execute()
    except Exception:
        logger.warning("replay_vision.enqueue_claim.release_failed", team_id=team_id, exc_info=True)


def pending_enqueue_claims_for_team(team_id: int) -> int:
    """Live claims for scans enqueued but not yet persisted."""
    return _pending(_team_key(team_id))


def pending_enqueue_claims_for_scanner(scanner_id: UUID) -> int:
    return _pending(_scanner_key(scanner_id))


def _pending(key: str) -> int:
    try:
        return int(redis.get_client().zcount(key, f"({time.time()}", "+inf"))
    except Exception:
        logger.warning("replay_vision.enqueue_claim.count_failed", key=key, exc_info=True)
        return 0
