import time
import random
from collections.abc import AsyncGenerator
from uuid import UUID

import orjson

from products.notifications.backend.pubsub import subscribe

SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
SSE_POLL_TIMEOUT_SECONDS = 1.0
SSE_MAX_DURATION_SECONDS = 15 * 60
# Tabs that connect together (for example, after a deploy) would otherwise rotate together every cycle.
SSE_MAX_DURATION_JITTER_SECONDS = 60.0


def _is_user_id(value: object, user_id: int) -> bool:
    # Go decodes JSON numbers as float64 and truncates before it compares, and it never matches
    # booleans or strings. Python treats True as 1, so exclude bool explicitly.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return int(value) == user_id


def filter_notification_for_user(payload: bytes | str, user_id: int) -> bytes | None:
    """Port of livestream's `filterNotificationForUser`.

    The channel carries every notification in the organization, so this is the only check that keeps
    a message from users it was not addressed to. Returns the payload to send, without
    `resolved_user_ids`, or None to drop the message.
    """
    try:
        data = orjson.loads(payload)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    resolved_user_ids = data.get("resolved_user_ids")
    if not isinstance(resolved_user_ids, list):
        return None
    if not any(_is_user_id(value, user_id) for value in resolved_user_ids):
        return None
    del data["resolved_user_ids"]
    return orjson.dumps(data)


async def notification_event_stream(organization_id: UUID, user_id: int) -> AsyncGenerator[bytes]:
    started_at = time.monotonic()
    max_duration = SSE_MAX_DURATION_SECONDS + random.uniform(0, SSE_MAX_DURATION_JITTER_SECONDS)
    async with subscribe(organization_id) as subscription:
        last_write = time.monotonic()
        while time.monotonic() - started_at < max_duration:
            message = await subscription.get_message(timeout=SSE_POLL_TIMEOUT_SECONDS)
            now = time.monotonic()
            if message and message.get("type") == "message":
                payload = filter_notification_for_user(message["data"], user_id)
                if payload is not None:
                    yield b"data: " + payload + b"\n\n"
                    last_write = now
            if now - last_write >= SSE_HEARTBEAT_INTERVAL_SECONDS:
                yield b": heartbeat\n\n"
                last_write = now
        yield b"event: end\ndata: reconnect\n\n"
