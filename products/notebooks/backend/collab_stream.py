"""
Shared Redis-stream transport for notebook collaboration.

One versioned content stream per notebook, with the stream id (`N-x`) carrying the
notebook version. Two writers share it, each in its own module:

- prosemirror-collab steps (`N-0`, payload has `step`) for rich v1 notebooks — `collab.py`
- markdown update events (`N-0` via CAS submit, `N-1` via post-save publish; payload has
  `type: "update"` and optionally a `diff`) for markdown notebooks — `markdown_collab.py`

This module owns the stream key layout, the version-CAS Lua script both writers append
with, and the SSE tailer that fans both event kinds (plus presence, see `presence.py`)
out to clients.
"""

import json
import time
import asyncio
from collections.abc import AsyncGenerator

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

from products.notebooks.backend.presence import PRESENCE_BACKFILL_MS, PRESENCE_STREAM_KEY_PATTERN, presence_sse_frame

logger = structlog.get_logger(__name__)

STREAM_KEY_PATTERN = "notebook:collab:{{{team_id}:{notebook_id}}}:stream"

STREAM_TTL_SECONDS = 60 * 60 * 24  # 1 day, refreshed on every XADD
STREAM_MAX_LENGTH = 5000  # ~hour of heavy editing
STREAM_READ_COUNT = 32

# Max XREAD wait, proxies idle-kill connections around 60s
STREAM_BLOCK_MS = 15_000

# SSE lifetime cap - browser auto-reconnects via Last-Event-ID
STREAM_LIFETIME_SECONDS = 5 * 60

DATA_KEY = b"data"
KEEPALIVE_COMMENT = b": keepalive\n\n"
UPDATE_EVENT_TYPE = "update"

# Atomically append N content entries if the current stream version equals last_seen_version.
#
# When the stream is empty (TTL expired / evicted / never written) we cannot trust the caller's
# last_seen_version on its own — a stale tab with an old baseline could otherwise be accepted
# and silently downgrade the persisted version on the subsequent Notebook update. Cross-check
# against last_saved_version (the value durably stored in Postgres): only accept if they match
# exactly, otherwise force the client to reload.
#
# ARGV:
#   1: last_seen_version (int)         -- confirmed version on the client
#   2: last_saved_version (int)        -- notebook.version from Postgres, fetched by the caller
#   3: ttl_seconds (int)
#   4: max_length (int)
#   5..N: entry JSON strings (one per step / update event)
#
# Returns:
#   {0, current_stream_version}        -- conflict, caller should fetch the missed range
#   {1, new_version}                   -- accepted
#   {2, last_saved_version}            -- stream lost + client baseline disagrees with Postgres → stale
APPEND_ENTRIES_LUA = """
local stream_key = KEYS[1]
local last_seen_version = tonumber(ARGV[1])
local last_saved_version = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local max_length = tonumber(ARGV[4])

local current_stream_version = last_seen_version
local last = redis.call('XREVRANGE', stream_key, '+', '-', 'COUNT', 1)
local stream_empty = (#last == 0)
if not stream_empty then
    local id_str = last[1][1]
    local dash = string.find(id_str, '-')
    current_stream_version = tonumber(string.sub(id_str, 1, dash - 1))
end

if stream_empty and last_seen_version ~= last_saved_version then
    return {2, last_saved_version}
end

if current_stream_version ~= last_seen_version then
    -- A failed XADD (publish errors are logged, not raised) can leave the stream behind
    -- Postgres. When the caller's baseline matches Postgres, resync forward instead of
    -- rejecting every save against a permanently lagging stream.
    if current_stream_version < last_seen_version and last_seen_version == last_saved_version then
        current_stream_version = last_seen_version
    else
        return {0, current_stream_version}
    end
end

local next_version = current_stream_version
for i = 5, #ARGV do
    next_version = next_version + 1
    redis.call('XADD', stream_key, 'MAXLEN', '~', max_length, next_version .. '-0', 'data', ARGV[i])
end

redis.call('EXPIRE', stream_key, ttl)
return {1, next_version}
"""


async def stream_collab_sse(
    team_id: int,
    notebook_id: str,
    *,
    last_event_id: str | None,
) -> AsyncGenerator[bytes]:
    """
    Tail this notebook's content and presence Redis streams from last_event_id (or from now
    if None). Yields one SSE frame per step/update/presence event, plus a keepalive comment
    during idle gaps.

    Only content frames carry an `id:` line — Last-Event-ID must resume the versioned content
    stream, never the ephemeral presence stream (which backfills the last few seconds instead).
    """
    client = redis_module.get_async_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)
    presence_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    content_id = last_event_id
    if content_id is None:
        # Resolve "now" to a concrete id up front: with two streams in one XREAD, "$" would
        # re-evaluate on every call and skip content appended while a presence batch was
        # being processed.
        try:
            newest = await client.xrevrange(stream_key, "+", "-", count=1)
            content_id = newest[0][0].decode() if newest else "0-0"
        except redis_exceptions.RedisError as err:
            logger.warning("notebook_collab_stream_error", notebook_short_id=notebook_id, error=str(err))
            yield b'event: error\ndata: {"error":"stream error"}\n\n'
            return
    presence_id = f"{max(0, int(time.time() * 1000) - PRESENCE_BACKFILL_MS)}-0"

    try:
        async with asyncio.timeout(STREAM_LIFETIME_SECONDS):
            while True:
                try:
                    messages = await client.xread(
                        {stream_key: content_id, presence_key: presence_id},
                        block=STREAM_BLOCK_MS,
                        count=STREAM_READ_COUNT,
                    )
                except redis_exceptions.RedisError as err:
                    logger.warning("notebook_collab_stream_error", notebook_short_id=notebook_id, error=str(err))
                    yield b'event: error\ndata: {"error":"stream error"}\n\n'
                    return

                if not messages:
                    yield KEEPALIVE_COMMENT
                    continue

                for key, entries in messages:
                    key_name = key.decode() if isinstance(key, bytes) else key
                    if key_name == presence_key:
                        for stream_id, fields in entries:
                            presence_id = stream_id.decode()
                            frame = presence_sse_frame(fields, stream_key=presence_key, stream_id=presence_id)
                            if frame is not None:
                                yield frame
                        continue

                    for stream_id, fields in entries:
                        content_id = stream_id.decode()
                        try:
                            data = json.loads(fields[DATA_KEY])
                        except json.JSONDecodeError:
                            logger.warning(
                                "notebook_collab_invalid_payload", stream_key=stream_key, stream_id=content_id
                            )
                            continue
                        event_type = data.get("type")
                        if event_type == UPDATE_EVENT_TYPE:
                            yield (
                                f"id: {content_id}\nevent: update\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
                            ).encode()
                        elif "step" in data:
                            yield (
                                f"id: {content_id}\nevent: step\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
                            ).encode()
                        else:
                            logger.warning(
                                "notebook_collab_unknown_payload", stream_key=stream_key, stream_id=content_id
                            )

                # cooperative yield: prevents tight-loop monopolization when XREAD doesn't block
                await asyncio.sleep(0)
    except TimeoutError:
        # Lifetime cap hit; client reconnects with Last-Event-ID against a fresh worker
        return
