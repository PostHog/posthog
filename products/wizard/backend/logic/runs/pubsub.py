from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from django.db import transaction

import structlog
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from posthog.redis import get_async_client, get_client

logger = structlog.get_logger(__name__)


def channel_name(team_id: int, run_id: UUID) -> str:
    return f"wizard_runs:team:{team_id}:run:{run_id}"


def publish_run_update(team_id: int, run_id: UUID) -> None:
    def publish() -> None:
        try:
            # Subscribers reload committed state so delayed notifications cannot replay an older snapshot.
            get_client().publish(channel_name(team_id, run_id), b"{}")
        except RedisError:
            logger.exception("wizard_run_publish_failed", team_id=team_id, run_id=str(run_id))

    transaction.on_commit(publish)


@asynccontextmanager
async def subscribe(team_id: int, run_id: UUID) -> AsyncIterator[PubSub]:
    client = get_async_client()
    async with client.pubsub(ignore_subscribe_messages=True) as pubsub:
        await pubsub.subscribe(channel_name(team_id, run_id))
        yield pubsub
