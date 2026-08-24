"""Atomic enqueue-slot claims for on-demand scans.

The in-flight caps count ReplayObservation rows, but a row only appears once the apply workflow's
first activity runs, so concurrent requests could race past the caps in that gap. A claim is taken
atomically (single Lua eval, same shape as posthog/clickhouse/client/limit.py) before the workflow
starts and decays once the row exists. Fail-open: the caps are backpressure guardrails, not billing.
"""

import time
from uuid import UUID

import structlog

from posthog import redis

from products.replay_vision.backend.temporal.constants import (
    MAX_IN_FLIGHT_APPLIES_PER_BACKFILL,
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    ON_DEMAND_RESERVED_SCANNER_SLOTS,
    ON_DEMAND_RESERVED_TEAM_SLOTS,
)
from products.replay_vision.backend.temporal.metrics import record_enqueue_claim_failure

logger = structlog.get_logger(__name__)

# Must exceed worst-case enqueue-to-first-activity lag; crashed claims are reclaimed after this long.
_CLAIM_TTL_SECONDS = 15 * 60

# Decay window: claim and just-persisted row overlap, so stale row counts can't under-count.
_RELEASE_GRACE_SECONDS = 60

_TEAM_KEY_PREFIX = "@posthog/replay-vision/enqueued-team"
_SCANNER_KEY_PREFIX = "@posthog/replay-vision/enqueued-scanner"
_BACKFILL_KEY_PREFIX = "@posthog/replay-vision/enqueued-backfill"

# Re-claiming an existing member (same deterministic workflow id) never consumes a second slot.
# Generalized over KEYS: each key is one cap the claim must fit, with its allowance in ARGV[3 + i].
# Callers pass team and scanner; a backfill adds its own sub-cap key as a third.
_CLAIM_LUA = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local ttl = tonumber(ARGV[3])

for i, key in ipairs(KEYS) do
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
end

if not redis.call('ZSCORE', KEYS[1], member) then
    for i, key in ipairs(KEYS) do
        if redis.call('ZCARD', key) >= tonumber(ARGV[3 + i]) then
            return 0
        end
    end
end

local expiry = now + ttl
for i, key in ipairs(KEYS) do
    redis.call('ZADD', key, expiry, member)
    redis.call('EXPIRE', key, ttl)
end
return 1
"""


def _team_key(team_id: int) -> str:
    return f"{_TEAM_KEY_PREFIX}:{team_id}"


def _scanner_key(scanner_id: UUID) -> str:
    return f"{_SCANNER_KEY_PREFIX}:{scanner_id}"


def _backfill_key(backfill_id: UUID) -> str:
    return f"{_BACKFILL_KEY_PREFIX}:{backfill_id}"


def try_claim_enqueue_slot(
    *,
    team_id: int,
    scanner_id: UUID,
    workflow_id: str,
    team_in_flight_rows: int,
    scanner_in_flight_rows: int,
    backfill_id: UUID | None = None,
    backfill_in_flight_rows: int = 0,
    scheduled: bool = False,
) -> bool:
    """Atomically claim one enqueue slot against every in-flight cap; True when the scan may start.

    Passing `backfill_id` also holds the claim against that backfill's sub-cap, so successive ticks
    see the slots an earlier tick took before its children persisted their rows. `scheduled` claims
    stop at the reserved ceilings, so racing scheduled dispatchers cannot eat the on-demand reserve.
    """
    team_cap = MAX_IN_FLIGHT_APPLIES_PER_TEAM - (ON_DEMAND_RESERVED_TEAM_SLOTS if scheduled else 0)
    scanner_cap = MAX_IN_FLIGHT_APPLIES_PER_SCANNER - (ON_DEMAND_RESERVED_SCANNER_SLOTS if scheduled else 0)
    keys = [_team_key(team_id), _scanner_key(scanner_id)]
    allowances = [
        team_cap - team_in_flight_rows,
        scanner_cap - scanner_in_flight_rows,
    ]
    if backfill_id is not None:
        keys.append(_backfill_key(backfill_id))
        allowances.append(MAX_IN_FLIGHT_APPLIES_PER_BACKFILL - backfill_in_flight_rows)
    try:
        allowed = redis.get_client().eval(
            _CLAIM_LUA,
            len(keys),
            *keys,
            time.time(),
            workflow_id,
            _CLAIM_TTL_SECONDS,
            *allowances,
        )
        return bool(allowed)
    except Exception:
        record_enqueue_claim_failure("claim")
        logger.warning("replay_vision.enqueue_claim.failed_open", team_id=team_id, exc_info=True)
        return True


def claim_enqueue_slot_prefix(
    *,
    team_id: int,
    scanner_id: UUID,
    workflow_ids: list[str],
    team_in_flight_rows: int,
    scanner_in_flight_rows: int,
    backfill_id: UUID | None = None,
    backfill_in_flight_rows: int = 0,
    scheduled: bool = False,
) -> int:
    """Claim slots for an ordered batch, returning how many leading ids were admitted.

    The batch variant of `claim_apply_scanner_slot` (which is per-request and re-reads the caps after
    each claim, far too many queries for a 50-wide fan-out). One row-count read is shared across the
    batch, which is sound because the Lua script counts claims taken earlier in the same loop itself.

    Stops at the first refusal instead of skipping ahead, so the admitted set is always a prefix of
    the caller's ordering. A keyset walk can then advance its cursor to the last admitted item and
    retry the rest, rather than stepping over sessions that were never dispatched.
    """
    for admitted, workflow_id in enumerate(workflow_ids):
        if not try_claim_enqueue_slot(
            team_id=team_id,
            scanner_id=scanner_id,
            workflow_id=workflow_id,
            team_in_flight_rows=team_in_flight_rows,
            scanner_in_flight_rows=scanner_in_flight_rows,
            backfill_id=backfill_id,
            backfill_in_flight_rows=backfill_in_flight_rows,
            scheduled=scheduled,
        ):
            return admitted
    return len(workflow_ids)


def release_enqueue_claim(
    *,
    team_id: int,
    scanner_id: UUID,
    workflow_id: str,
    immediately: bool = False,
    backfill_id: UUID | None = None,
) -> None:
    """Decay a claim once its observation row exists (or the start failed); unreleased claims
    self-expire. `immediately` removes it outright, for claims that never covered anything."""
    expiry = time.time() + _RELEASE_GRACE_SECONDS
    try:
        keys = [_team_key(team_id), _scanner_key(scanner_id)]
        if backfill_id is not None:
            keys.append(_backfill_key(backfill_id))
        pipeline = redis.get_client().pipeline()
        for key in keys:
            if immediately:
                pipeline.zrem(key, workflow_id)
            else:
                pipeline.zadd(key, {workflow_id: expiry}, xx=True)
        pipeline.execute()
    except Exception:
        record_enqueue_claim_failure("release")
        logger.warning("replay_vision.enqueue_claim.release_failed", team_id=team_id, exc_info=True)


def pending_enqueue_claims_for_team(team_id: int) -> int:
    """Live claims for scans enqueued but not yet persisted."""
    return _pending(_team_key(team_id))


def pending_enqueue_claims_for_backfill(backfill_id: UUID) -> int:
    return _pending(_backfill_key(backfill_id))


def pending_enqueue_claims_for_scanner(scanner_id: UUID) -> int:
    return _pending(_scanner_key(scanner_id))


def pending_enqueue_claims(team_id: int, scanner_id: UUID, backfill_id: UUID | None = None) -> dict[str, int]:
    """The three claim counts a cap check needs, in one round-trip instead of three."""
    keys = {"team": _team_key(team_id), "scanner": _scanner_key(scanner_id)}
    if backfill_id is not None:
        keys["backfill"] = _backfill_key(backfill_id)
    try:
        pipeline = redis.get_client().pipeline()
        cutoff = f"({time.time()}"
        for key in keys.values():
            pipeline.zcount(key, cutoff, "+inf")
        return dict(zip(keys, (int(count) for count in pipeline.execute())))
    except Exception:
        record_enqueue_claim_failure("count")
        logger.warning("replay_vision.enqueue_claim.count_failed", keys=list(keys.values()), exc_info=True)
        return dict.fromkeys(keys, 0)


def _pending(key: str) -> int:
    try:
        return int(redis.get_client().zcount(key, f"({time.time()}", "+inf"))
    except Exception:
        record_enqueue_claim_failure("count")
        logger.warning("replay_vision.enqueue_claim.count_failed", key=key, exc_info=True)
        return 0
