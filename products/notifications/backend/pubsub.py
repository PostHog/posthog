import time
import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any
from uuid import UUID

import orjson
import structlog
from redis.asyncio.client import PubSub

from posthog.redis import get_async_client, get_client

logger = structlog.get_logger(__name__)

_PUBLISH_SOCKET_TIMEOUT_SECONDS = 0.5
_PUBLISH_PAUSE_AFTER_FAILURE_SECONDS = 30.0

_SUBSCRIPTION_QUEUE_SIZE = 256
# Keep this below REDIS_SOCKET_TIMEOUT_SECONDS. A read that waits for the socket timeout makes redis-py drop the
# connection and open a new one.
_HUB_READ_TIMEOUT_SECONDS = 10.0


class NotificationSubscriptionError(Exception):
    pass


def notifications_channel(organization_id: UUID | str, user_id: int) -> str:
    # Livestream fans out on `notifications:<org_id>` in its own Redis. This name differs so that
    # nobody mistakes the two transports for one channel.
    return f"notifications:org:{organization_id}:user:{user_id}"


class _Publisher:
    def __init__(self) -> None:
        self.paused_until = 0.0

    def publish(self, organization_id: UUID | str, payload: dict[str, Any]) -> None:
        user_ids = payload.get("resolved_user_ids") or []
        if not user_ids or time.monotonic() < self.paused_until:
            return
        message = orjson.dumps({key: value for key, value in payload.items() if key != "resolved_user_ids"})
        try:
            client = get_client(
                socket_timeout=_PUBLISH_SOCKET_TIMEOUT_SECONDS,
                socket_connect_timeout=_PUBLISH_SOCKET_TIMEOUT_SECONDS,
            )
            pipeline = client.pipeline(transaction=False)
            for user_id in user_ids:
                pipeline.publish(notifications_channel(organization_id, user_id), message)
            pipeline.execute()
        except Exception:
            self.paused_until = time.monotonic() + _PUBLISH_PAUSE_AFTER_FAILURE_SECONDS
            logger.exception("notifications.redis_publish_failed", organization_id=str(organization_id))


_publisher = _Publisher()


def publish_notification_payload(organization_id: UUID | str, payload: dict[str, Any]) -> None:
    """Publish the payload, without `resolved_user_ids`, to the channel of each user in that list.

    Best effort, so a Redis failure cannot break notification creation or the Kafka publish next to it.
    """
    _publisher.publish(organization_id, payload)


class NotificationSubscription:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=_SUBSCRIPTION_QUEUE_SIZE)

    def deliver(self, message: bytes) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            self.fail()

    def fail(self) -> None:
        while True:
            try:
                self._queue.put_nowait(None)
                return
            except asyncio.QueueFull:
                self._queue.get_nowait()

    async def receive(self, timeout: float) -> bytes | None:
        try:
            message = await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None
        if message is None:
            raise NotificationSubscriptionError("The notifications subscription lost its Redis connection.")
        return message


class _NotificationHub:
    """One Redis pub/sub connection for all notification streams on one event loop.

    A channel stays subscribed while at least one stream needs it, and one reader task puts each message in the
    queues of that channel. When a Redis error stops the reader, every subscription fails, so each client
    reconnects and refetches what it missed.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pubsub: PubSub | None = None
        self._reader: asyncio.Task[None] | None = None
        self._subscriptions: dict[str, set[NotificationSubscription]] = {}

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[NotificationSubscription]:
        subscription = NotificationSubscription()
        async with self._lock:
            if self._pubsub is None:
                self._pubsub = get_async_client().pubsub(ignore_subscribe_messages=True)
            pubsub = self._pubsub
            try:
                if channel not in self._subscriptions:
                    await pubsub.subscribe(channel)
                    self._subscriptions[channel] = set()
            except Exception:
                await self._close(pubsub, self._detach(pubsub))
                raise
            self._subscriptions[channel].add(subscription)
            if self._reader is None:
                self._reader = asyncio.create_task(self._read(pubsub))
        try:
            yield subscription
        finally:
            await self._unsubscribe(channel, subscription)

    async def _unsubscribe(self, channel: str, subscription: NotificationSubscription) -> None:
        async with self._lock:
            pubsub = self._pubsub
            subscriptions = self._subscriptions.get(channel)
            if pubsub is None or subscriptions is None:
                return
            subscriptions.discard(subscription)
            if subscriptions:
                return
            del self._subscriptions[channel]
            if not self._subscriptions:
                await self._close(pubsub, self._detach(pubsub))
                return
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                await self._close(pubsub, self._detach(pubsub))

    async def _read(self, pubsub: PubSub) -> None:
        try:
            while True:
                message = await pubsub.get_message(timeout=_HUB_READ_TIMEOUT_SECONDS)
                if message is None or message.get("type") != "message":
                    continue
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                for subscription in self._subscriptions.get(channel, ()):
                    subscription.deliver(message["data"])
        except Exception:
            logger.exception("notifications.redis_subscriber_failed")
            async with self._lock:
                orphans = self._detach(pubsub)
            await self._close(pubsub, orphans)

    def _detach(self, pubsub: PubSub) -> list[NotificationSubscription]:
        # The caller holds self._lock.
        if self._pubsub is not pubsub:
            return []
        if self._reader is not None and self._reader is not asyncio.current_task():
            self._reader.cancel()
        self._pubsub = None
        self._reader = None
        orphans = [subscription for subscriptions in self._subscriptions.values() for subscription in subscriptions]
        self._subscriptions = {}
        return orphans

    async def _close(self, pubsub: PubSub, orphans: list[NotificationSubscription]) -> None:
        for subscription in orphans:
            subscription.fail()
        with suppress(Exception):
            await pubsub.close()


# The async Redis client is bound to one event loop, so each loop gets its own hub.
_hubs: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _NotificationHub]" = weakref.WeakKeyDictionary()


@asynccontextmanager
async def subscribe_to_notifications(
    organization_id: UUID | str, user_id: int
) -> AsyncIterator[NotificationSubscription]:
    loop = asyncio.get_running_loop()
    hub = _hubs.get(loop)
    if hub is None:
        hub = _hubs[loop] = _NotificationHub()
    async with hub.subscribe(notifications_channel(organization_id, user_id)) as subscription:
        yield subscription
