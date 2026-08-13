"""Incrementally-maintained blocked-session sets for scanners with negative filters.

A scanner with a negative filter ("host is not X") must not observe any session containing a
disqualifying event. Instead of re-scanning the full events lookback for those sessions on every
sweep tick (the `globalNotIn` blocklist subquery), each tick scans only events *ingested* since the
last scan — arrival time is monotone, so an advancing `inserted_at` watermark covers every event
exactly, including late arrivals — and folds the matched session ids into a Redis sorted set on the
dedicated replay-vision instance. The candidate query then skips its blocklist subqueries and the
sweep drops blocked candidates after the fetch.

The set is a derived structure: the watermark and a fingerprint of the negative filters live next to
it, and any mismatch, gap, or Redis loss triggers one full-width rebuild scan before the incremental
path is trusted again. Failures fall back to the legacy in-query blocklist, which is always correct.
"""

import json
import hashlib
import datetime as dt
from dataclasses import dataclass

from django.conf import settings

import redis
import structlog

from posthog.schema import RecordingsQuery

from posthog.models import Team
from posthog.redis import get_client
from posthog.session_recordings.queries.sub_queries.events_subquery import (
    ReplayFiltersEventsSubQuery,
    test_accounts_only_query,
)
from posthog.session_recordings.queries.utils import expand_test_account_filters

from products.replay_vision.backend.queries.scanner_candidate_query import _PARTITION_LOOKBACK, _execute_candidate_query

logger = structlog.get_logger(__name__)

# Entries older than the candidate lookback can never block a candidate again.
_RETENTION = _PARTITION_LOOKBACK + dt.timedelta(hours=1)
_KEY_TTL_SECONDS = int((_RETENTION + dt.timedelta(hours=1)).total_seconds())
# Each delta re-scans a little of the covered range so clock skew between nodes can't open a gap.
_DELTA_OVERLAP = dt.timedelta(minutes=5)
# The watermark trails the clock by this much. `inserted_at` is stamped by the shard that wrote the
# row, so a row can exist with a timestamp the reader cannot see yet through replication lag or an
# unmerged part. Advancing to wall-clock `now` would step over those rows for good.
_VISIBILITY_LAG = dt.timedelta(minutes=45)
# A candidate session can start up to the SDK's 24h rotation before it ends, and the store only
# covers events back to the rebuild horizon. Past this lag the oldest candidate's events fall outside
# that coverage, so the scanner keeps the in-query blocklist instead.
_MAX_WATERMARK_LAG = _PARTITION_LOOKBACK - dt.timedelta(hours=24)
# A watermark this stale (worker outage, long throttle) is rebuilt rather than delta-scanned.
_MAX_DELTA_GAP = dt.timedelta(hours=6)
# Above this the set stops being cheap to hold and check; the scanner falls back to the legacy
# in-query blocklist, whose cost the read guardrail then prices.
_MAX_ENTRIES = 1_000_000
# Mirrors the legacy blocklist subquery LIMIT: a scan that fills it can't be trusted as complete.
_SCAN_LIMIT = 1_000_000

_SESSIONS_KEY = "@posthog/replay-vision/blocked-sessions/{scanner_id}"
_META_KEY = "@posthog/replay-vision/blocked-sessions/{scanner_id}/meta"


@dataclass(frozen=True, kw_only=True)
class _StoreState:
    watermark: dt.datetime | None
    fingerprint: str | None
    overflowed: bool
    # What the last write stored, versus what the set actually holds now. The two keys can be evicted
    # independently on a shared Redis, and a surviving meta over a lost set would report every session
    # as unblocked.
    entry_count: int
    live_count: int


def _redis() -> redis.Redis:
    return get_client(settings.REPLAY_VISION_REDIS_URL)


def _builders(team: Team, query: RecordingsQuery) -> list[ReplayFiltersEventsSubQuery]:
    builders = [ReplayFiltersEventsSubQuery(team, query)]
    if query.filter_test_accounts:
        filters = expand_test_account_filters(team)
        if filters:
            builders.append(ReplayFiltersEventsSubQuery(team, test_accounts_only_query(query, filters)))
    return builders


def blocklist_fingerprint(team: Team, query: RecordingsQuery) -> str | None:
    """Identity of the scanner's negative-filter set; None when no blocklist is needed.

    Test-account filters are team config that changes independently of the scanner, so they're part
    of the identity — an edit to either invalidates the stored set and forces a rebuild.
    """
    negative = [
        prop.model_dump(exclude_none=True)
        for builder in _builders(team, query)
        for prop in builder.negative_properties()
    ]
    if not negative:
        return None
    return hashlib.sha256(json.dumps(negative, sort_keys=True, default=str).encode()).hexdigest()[:16]


def refresh_blocked_sessions(
    *, scanner_id: str, team: Team, query: RecordingsQuery, fingerprint: str, last_swept_at: dt.datetime
) -> bool:
    """Bring the scanner's blocked set up to date; True when the set is usable this tick.

    False means the caller must keep the legacy in-query blocklist (overflow, scan-limit hit, or a
    Redis/query failure) — always safe, just at the old cost.
    """
    try:
        now = dt.datetime.now(dt.UTC)
        # A scanner this far behind would ask about sessions whose events predate the store's coverage,
        # and a miss there means observing a session the filter excludes. Buy back the old cost instead.
        if now - last_swept_at > _MAX_WATERMARK_LAG:
            return False

        state = _read_state(scanner_id)
        if state.fingerprint == fingerprint and state.overflowed:
            return False

        watermark = now - _VISIBILITY_LAG
        rebuild = (
            state.fingerprint != fingerprint
            or state.watermark is None
            or now - state.watermark > _MAX_DELTA_GAP
            # Fewer entries than the last write left behind means the set was evicted or trimmed
            # underneath us. Retention pruning only ever removes, so `<` and not `!=`.
            or state.live_count < state.entry_count
        )
        # `rebuild` already covers a missing watermark; the explicit check is what narrows the type.
        stored = state.watermark
        ingested_after = None if rebuild or stored is None else stored - _DELTA_OVERLAP
        session_ids = _scan(scanner_id, team, query, ingested_after=ingested_after)

        if session_ids is None:  # scan hit its limit; completeness can't be trusted
            _write_overflow(scanner_id, fingerprint)
            return False

        return _write(scanner_id, fingerprint, watermark=watermark, session_ids=session_ids, clear=rebuild)
    except Exception:
        logger.exception("replay_vision.blocked_sessions_refresh_failed", scanner_id=scanner_id)
        return False


def blocked_subset(scanner_id: str, session_ids: list[str]) -> set[str]:
    """Which of `session_ids` are in the scanner's blocked set."""
    if not session_ids:
        return set()
    scores = _redis().zmscore(_SESSIONS_KEY.format(scanner_id=scanner_id), session_ids)
    return {session_id for session_id, score in zip(session_ids, scores) if score is not None}


def _scan(
    scanner_id: str, team: Team, query: RecordingsQuery, *, ingested_after: dt.datetime | None
) -> list[str] | None:
    """Blocked session ids across all builders; None when any scan filled its limit."""
    session_ids: list[str] = []
    # Both paths get the same window, bounded like the candidate query's inner scan. A delta that
    # inherited the scanner's own narrower range would miss an event that arrives now carrying an old
    # timestamp, which is exactly the case an arrival-time scan exists to catch.
    scan_query = query.model_copy(deep=True)
    scan_query.date_from = (dt.datetime.now(dt.UTC) - _PARTITION_LOOKBACK).isoformat()
    scan_query.date_to = None

    for builder in _builders(team, scan_query):
        # Built to sit inside a globalNotIn, but already a complete SELECT of session ids standalone.
        blocklist = builder.get_negative_blocklist_query(ingested_after=ingested_after)
        if blocklist is None:
            continue
        rows = _execute_candidate_query(
            blocklist,
            team=team,
            query_type="ReplayVisionBlocklistDeltaQuery" if ingested_after else "ReplayVisionBlocklistRebuildQuery",
            max_execution_time_seconds=180,
            scanner_id=scanner_id,
        )
        if len(rows) >= _SCAN_LIMIT:
            return None
        session_ids.extend(row[0] for row in rows)
    return session_ids


def _read_state(scanner_id: str) -> _StoreState:
    client = _redis()
    pipe = client.pipeline(transaction=True)
    pipe.hgetall(_META_KEY.format(scanner_id=scanner_id))
    pipe.zcard(_SESSIONS_KEY.format(scanner_id=scanner_id))
    meta, live_count = pipe.execute()
    decoded = {k.decode(): v.decode() for k, v in meta.items()}
    watermark = None
    if raw := decoded.get("watermark"):
        try:
            watermark = dt.datetime.fromisoformat(raw)
        except ValueError:
            watermark = None
    try:
        entry_count = int(decoded.get("entry_count", 0))
    except ValueError:
        entry_count = 0
    return _StoreState(
        watermark=watermark,
        fingerprint=decoded.get("fingerprint") or None,
        overflowed=decoded.get("overflowed") == "1",
        entry_count=entry_count,
        live_count=int(live_count),
    )


def _write(scanner_id: str, fingerprint: str, *, watermark: dt.datetime, session_ids: list[str], clear: bool) -> bool:
    sessions_key = _SESSIONS_KEY.format(scanner_id=scanner_id)
    meta_key = _META_KEY.format(scanner_id=scanner_id)
    client = _redis()
    score = watermark.timestamp()

    pipe = client.pipeline(transaction=True)
    if clear:
        pipe.delete(sessions_key)
    if session_ids:
        pipe.zadd(sessions_key, dict.fromkeys(session_ids, score))
    pipe.zremrangebyscore(sessions_key, "-inf", (watermark - _RETENTION).timestamp())
    pipe.expire(sessions_key, _KEY_TTL_SECONDS)
    pipe.expire(meta_key, _KEY_TTL_SECONDS)
    pipe.zcard(sessions_key)
    entry_count = pipe.execute()[-1]

    if entry_count > _MAX_ENTRIES:
        _write_overflow(scanner_id, fingerprint)
        return False
    # Recorded after the fact so the next read can tell a pruned set from an evicted one.
    client.hset(
        meta_key,
        mapping={
            "watermark": watermark.isoformat(),
            "fingerprint": fingerprint,
            "overflowed": "0",
            "entry_count": entry_count,
        },
    )
    client.expire(meta_key, _KEY_TTL_SECONDS)
    return True


def _write_overflow(scanner_id: str, fingerprint: str) -> None:
    client = _redis()
    pipe = client.pipeline(transaction=True)
    pipe.delete(_SESSIONS_KEY.format(scanner_id=scanner_id))
    meta_key = _META_KEY.format(scanner_id=scanner_id)
    pipe.hset(meta_key, mapping={"watermark": "", "fingerprint": fingerprint, "overflowed": "1"})
    pipe.expire(meta_key, _KEY_TTL_SECONDS)
    pipe.execute()
    logger.warning("replay_vision.blocked_sessions_overflowed", scanner_id=scanner_id)
