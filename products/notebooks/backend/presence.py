"""
Ephemeral caret/presence broadcasting for notebook collaboration.

Presence lives in its own Redis stream per notebook: the content stream's ids ARE
document versions (a CAS invariant), so presence can't share it. Ids here are
auto-generated and entries are short-lived — receivers always render the latest
ping per client and TTL-prune the rest, so a dropped event self-heals on the next one.
"""

import json
from typing import Any

import structlog
import redis.exceptions as redis_exceptions

from posthog import redis as redis_module

logger = structlog.get_logger(__name__)

PRESENCE_STREAM_KEY_PATTERN = "notebook:collab:{{{team_id}:{notebook_id}}}:presence"

PRESENCE_TTL_SECONDS = 60 * 5
PRESENCE_MAX_LENGTH = 256
# On connect, replay this much recent presence so a fresh tab sees existing carets immediately.
PRESENCE_BACKFILL_MS = 10_000

PRESENCE_EVENT_TYPE = "presence"

_DATA_KEY = b"data"


def publish_presence(
    team_id: int,
    notebook_id: str,
    *,
    client_id: str,
    user_id: int,
    user_name: str,
    version: int,
    cursor: dict[str, Any],
) -> None:
    """Fire-and-forget caret broadcast. Lossy by design: receivers always render the latest
    ping per client and TTL-prune the rest, so a dropped event self-heals on the next one."""
    client = redis_module.get_client()
    stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, notebook_id=notebook_id)
    payload = {
        "type": PRESENCE_EVENT_TYPE,
        "client_id": client_id,
        "user_id": user_id,
        "user_name": user_name,
        "version": version,
        "cursor": cursor,
    }

    try:
        client.xadd(
            stream_key,
            {"data": json.dumps(payload, separators=(",", ":"))},
            maxlen=PRESENCE_MAX_LENGTH,
            approximate=True,
        )
        client.expire(stream_key, PRESENCE_TTL_SECONDS)
    except redis_exceptions.RedisError as err:
        logger.warning(
            "notebook_collab_presence_publish_error",
            stream_key=stream_key,
            notebook_short_id=notebook_id,
            error=str(err),
        )


def presence_sse_frame(fields: dict[bytes, bytes], *, stream_key: str, stream_id: str) -> bytes | None:
    """Presence frames deliberately omit the `id:` line so they never disturb Last-Event-ID."""
    try:
        data = json.loads(fields[_DATA_KEY])
    except (json.JSONDecodeError, KeyError):
        logger.warning("notebook_collab_invalid_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    if data.get("type") != PRESENCE_EVENT_TYPE:
        logger.warning("notebook_collab_unknown_payload", stream_key=stream_key, stream_id=stream_id)
        return None
    return f"event: presence\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()
