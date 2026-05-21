"""
Redis-stream backed buffer for prosemirror-collab steps.
"""

import json
import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

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


@dataclass
class StepEntry:
    step: dict
    client_id: str


@dataclass
class SubmitResult:
    # "accepted" - steps appended; `version` is the new top
    # "conflict" - caller is behind; `version` is the current top, `steps_since` is the missed range
    # "stale"    - missed range was trimmed (MAXLEN/TTL); caller must reload from Postgres
    status: Literal["accepted", "conflict", "stale"]
    version: int
    steps_since: list[StepEntry] | None = None


# Atomically append N step entries if the latest stream version equals last_seen_version.
# If the stream is empty we trust the caller's last_seen_version,
# frontend always loads it from Postgres and seed the stream from there.
#
# ARGV:
#   1: last_seen_version (int)
#   2: ttl_seconds (int)
#   3: max_length (int)
#   4..N: step entry JSON strings (one per prosemirror step)
#
# Returns:
#   {0, current_version}     -- conflict, caller should fetch missed steps
#   {1, new_version}         -- accepted
_APPEND_STEPS_LUA = """
local stream_key = KEYS[1]
local last_seen_version = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local max_length = tonumber(ARGV[3])

local current_version = last_seen_version
local last = redis.call('XREVRANGE', stream_key, '+', '-', 'COUNT', 1)
if #last > 0 then
    local id_str = last[1][1]
    local dash = string.find(id_str, '-')
    current_version = tonumber(string.sub(id_str, 1, dash - 1))
end

if current_version ~= last_seen_version then
    return {0, current_version}
end

local next_version = current_version
for i = 4, #ARGV do
    next_version = next_version + 1
    redis.call('XADD', stream_key, 'MAXLEN', '~', max_length, next_version .. '-0', 'data', ARGV[i])
end

redis.call('EXPIRE', stream_key, ttl)
return {1, next_version}
"""


def submit_steps(
    team_id: int,
    notebook_id: str,
    client_id: str,
    steps_json: list[dict],
    last_seen_version: int,
    *,
    user_id: int | None = None,
    user_name: str | None = None,
    cursor_head: int | None = None,
) -> SubmitResult:
    client = redis_module.get_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)

    # Presence (author + cursor) is constant for the whole batch — build once, spread per step.
    presence: dict[str, Any] = {
        k: v for k, v in (("user_id", user_id), ("user_name", user_name), ("cursor_head", cursor_head)) if v is not None
    }
    # Version isn't in the payload — the stream id (N-0) IS the version, and SSE delivers it as `id:`.
    serialized = [json.dumps({"step": step, "client_id": client_id, **presence}) for step in steps_json]

    script = client.register_script(_APPEND_STEPS_LUA)
    accepted, version = script(
        keys=[stream_key],
        args=[last_seen_version, STREAM_TTL_SECONDS, STREAM_MAX_LENGTH, *serialized],
    )

    if accepted == 1:
        return SubmitResult(status="accepted", version=version)

    return _fetch_missed_steps(stream_key, last_seen_version=last_seen_version, current_version=version)


def _fetch_missed_steps(stream_key: str, *, last_seen_version: int, current_version: int) -> SubmitResult:
    client = redis_module.get_client()
    raw = client.xrange(stream_key, min=f"({last_seen_version}-0", max=f"{current_version}-0")

    missed_steps: list[StepEntry] = []
    for _stream_id, fields in raw:
        data = json.loads(fields[DATA_KEY])
        missed_steps.append(StepEntry(step=data["step"], client_id=data["client_id"]))

    # MAXLEN/TTL trimmed part of the gap - incomplete rebase set, reload from Postgres
    gap_size = current_version - last_seen_version
    if len(missed_steps) < gap_size:
        return SubmitResult(status="stale", version=current_version)

    return SubmitResult(status="conflict", version=current_version, steps_since=missed_steps)


async def stream_collab_sse(
    team_id: int,
    notebook_id: str,
    *,
    last_event_id: str | None,
) -> AsyncGenerator[bytes, None]:
    """
    Tail this notebook's Redis stream from last_event_id (or from now if None).
    Yields one SSE frame per step, plus a keepalive comment during idle gaps.
    """
    client = redis_module.get_async_client()
    stream_key = STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)
    current_id = last_event_id or "$"

    try:
        async with asyncio.timeout(STREAM_LIFETIME_SECONDS):
            while True:
                try:
                    messages = await client.xread(
                        {stream_key: current_id}, block=STREAM_BLOCK_MS, count=STREAM_READ_COUNT
                    )
                except redis_exceptions.RedisError as err:
                    logger.warning("notebook_collab_stream_error", notebook_short_id=notebook_id, error=str(err))
                    yield b'event: error\ndata: {"error":"stream error"}\n\n'
                    return

                if not messages:
                    yield KEEPALIVE_COMMENT
                    continue

                # We only XREAD one stream key, so messages is always [(key, entries)]
                _, entries = messages[0]
                for stream_id, fields in entries:
                    current_id = stream_id.decode()
                    try:
                        data = json.loads(fields[DATA_KEY])
                    except json.JSONDecodeError:
                        logger.warning("notebook_collab_invalid_payload", stream_key=stream_key, stream_id=current_id)
                        continue
                    yield f"id: {current_id}\nevent: step\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()

                # cooperative yield: prevents tight-loop monopolization when XREAD doesn't block
                await asyncio.sleep(0)
    except TimeoutError:
        # Lifetime cap hit; client reconnects with Last-Event-ID against a fresh worker
        return
