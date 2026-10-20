"""The region's copy of the hub's rules.

The sync job writes one Redis key with no TTL, so a hub outage never empties it. Each
process keeps the parsed, indexed rules in memory and checks the Redis version at most
every 30 seconds. When Redis is unreachable or empty, the process keeps what it has.
With nothing loaded at all, every decision is allow: nobody is blocked, and the login
email code stays required.
"""

import json
import time
import threading
from datetime import datetime

import structlog
from redis.commands.core import Script

from posthog.dataclasses import frozen
from posthog.redis import get_client

from ..metrics import LAST_SYNC_GAUGE, RULES_GAUGE, SKIPPED_RULES_COUNTER
from .matching import EMPTY_INDEX, RuleIndex, build_index
from .rules import SnapshotRule

logger = structlog.get_logger(__name__)

SNAPSHOT_KEY = "security:access_rules:snapshot"
VERSION_KEY = "security:access_rules:version"
LAST_SYNC_KEY = "security:access_rules:last_sync_at"
GENERATED_AT_KEY = "security:access_rules:generated_at"
MEMO_TTL_SECONDS = 30

# KEYS[1] generated-at key, KEYS[2] snapshot key, KEYS[3] version key.
# ARGV[1] this write's generatedAt (epoch ms, from the hub), ARGV[2] snapshot
# JSON, ARGV[3] version. Applies unless a stored generatedAt is already newer,
# so a slower, older fetch can't overwrite a snapshot a later one already
# stored. The hub is one deployment, so its own generatedAt orders writes
# without a counter this store would have to keep in sync: a missing key
# (never written, or flushed) simply means apply, so nothing can wedge.
_WRITE_LUA = """
local stored = tonumber(redis.call('GET', KEYS[1]))
local generated_at = tonumber(ARGV[1])
if stored ~= nil and generated_at < stored then
    return 0
end
redis.call('SET', KEYS[2], ARGV[2])
redis.call('SET', KEYS[3], ARGV[3])
redis.call('SET', KEYS[1], generated_at)
return 1
"""

_write_script: Script | None = None


@frozen
class WriteOutcome:
    applied: bool
    # None for a dropped write: its count was never applied, so it isn't the store's count.
    rule_count: int | None


@frozen
class Snapshot:
    version: str
    index: RuleIndex
    rule_count: int


EMPTY_SNAPSHOT = Snapshot(version="", index=EMPTY_INDEX, rule_count=0)

_lock = threading.Lock()
_memo: Snapshot = EMPTY_SNAPSHOT
_checked_at: float | None = None


def _parse(raw_rules: list[object]) -> tuple[RuleIndex, int]:
    rules: list[SnapshotRule] = []
    for raw in raw_rules:
        rule = SnapshotRule.from_wire(raw)
        if rule is None:
            SKIPPED_RULES_COUNTER.inc()
        else:
            rules.append(rule)
    return build_index(rules), len(rules)


def _get_write_script() -> Script:
    global _write_script
    if _write_script is None:
        _write_script = get_client().register_script(_WRITE_LUA)
    return _write_script


def write_snapshot(version: str, raw_rules: list[object], generated_at_ms: int | None = None) -> WriteOutcome:
    if generated_at_ms is None:
        generated_at_ms = int(time.time() * 1000)
    _, count = _parse(raw_rules)
    payload = json.dumps({"version": version, "rules": raw_rules})
    applied = bool(
        _get_write_script()(
            keys=[GENERATED_AT_KEY, SNAPSHOT_KEY, VERSION_KEY], args=[generated_at_ms, payload, version]
        )
    )
    if not applied:
        logger.warning("security_access_rules_write_stale", generated_at_ms=generated_at_ms)
        return WriteOutcome(applied=False, rule_count=None)
    RULES_GAUGE.set(count)
    return WriteOutcome(applied=True, rule_count=count)


def _decode(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


def stored_version() -> str | None:
    return _decode(get_client().get(VERSION_KEY))


def mark_synced(now: datetime) -> None:
    get_client().set(LAST_SYNC_KEY, now.isoformat())


def last_synced_at() -> datetime | None:
    value = _decode(get_client().get(LAST_SYNC_KEY))
    return datetime.fromisoformat(value) if value else None


def _load(version: str) -> Snapshot | None:
    raw = _decode(get_client().get(SNAPSHOT_KEY))
    if raw is None:
        return None
    payload = json.loads(raw)
    if payload.get("version") != version or not isinstance(payload.get("rules"), list):
        return None
    index, count = _parse(payload["rules"])
    return Snapshot(version=version, index=index, rule_count=count)


def current_snapshot() -> Snapshot:
    global _memo, _checked_at
    # time.time(), not time.monotonic(): this repo's clock-freezing tool for tests
    # (time_machine) doesn't patch monotonic, so a frozen test clock would never
    # cross the memo window.
    now = time.time()
    if _checked_at is not None and now - _checked_at < MEMO_TTL_SECONDS:
        return _memo

    # Redis I/O and the index rebuild happen outside the lock, so a slow refresh doesn't stall other threads.
    starting_memo = _memo
    memo = starting_memo
    try:
        version = stored_version()
        if version and version != memo.version:
            loaded = _load(version)
            if loaded is not None:
                memo = loaded
        synced_at = last_synced_at()
        if synced_at is not None:
            LAST_SYNC_GAUGE.set(synced_at.timestamp())
    except Exception:
        logger.warning("security_access_rules_snapshot_read_failed", exc_info=True)

    with _lock:
        # Only commit if nothing advanced _memo while this refresh ran outside the lock.
        if _memo is starting_memo:
            _memo = memo
        RULES_GAUGE.set(_memo.rule_count)
        _checked_at = now
        return _memo


def reset_memo() -> None:
    global _memo, _checked_at
    with _lock:
        _memo = EMPTY_SNAPSHOT
        _checked_at = None
