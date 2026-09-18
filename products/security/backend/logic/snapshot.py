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

from posthog.dataclasses import frozen
from posthog.redis import get_client

from ..metrics import LAST_SYNC_GAUGE, RULES_GAUGE, SKIPPED_RULES_COUNTER
from .matching import EMPTY_INDEX, RuleIndex, build_index
from .rules import SnapshotRule

logger = structlog.get_logger(__name__)

SNAPSHOT_KEY = "security:access_rules:snapshot"
VERSION_KEY = "security:access_rules:version"
LAST_SYNC_KEY = "security:access_rules:last_sync_at"
MEMO_TTL_SECONDS = 30


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


def write_snapshot(version: str, raw_rules: list[object]) -> int:
    _, count = _parse(raw_rules)
    pipe = get_client().pipeline(transaction=True)
    pipe.set(SNAPSHOT_KEY, json.dumps({"version": version, "rules": raw_rules}))
    pipe.set(VERSION_KEY, version)
    pipe.execute()
    RULES_GAUGE.set(count)
    return count


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
    memo = _memo
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

    RULES_GAUGE.set(memo.rule_count)
    with _lock:
        _memo = memo
        _checked_at = now
    return memo


def reset_memo() -> None:
    global _memo, _checked_at
    with _lock:
        _memo = EMPTY_SNAPSHOT
        _checked_at = None
