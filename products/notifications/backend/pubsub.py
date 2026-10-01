from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import orjson
import structlog
from redis.asyncio.client import PubSub

from posthog.redis import get_async_client, get_client

logger = structlog.get_logger(__name__)


def notifications_channel(organization_id: UUID | str) -> str:
    # Livestream fans out on `notifications:<org_id>` in its own Redis. This name differs so that
    # nobody mistakes the two transports for one channel.
    return f"notifications:org:{organization_id}"


def publish_notification_payload(organization_id: UUID | str, payload: dict[str, Any]) -> None:
    # Call only after commit. Realtime delivery is best effort: a Redis failure must not break
    # notification creation or the Kafka publish that runs next to it.
    try:
        get_client().publish(notifications_channel(organization_id), orjson.dumps(payload))
    except Exception:
        logger.exception("notifications.redis_publish_failed", organization_id=str(organization_id))


@asynccontextmanager
async def subscribe(organization_id: UUID | str) -> AsyncIterator[PubSub]:
    client = get_async_client()
    async with client.pubsub(ignore_subscribe_messages=True) as pubsub:
        await pubsub.subscribe(notifications_channel(organization_id))
        yield pubsub
