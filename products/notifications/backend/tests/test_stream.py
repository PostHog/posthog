import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
from redis.exceptions import ConnectionError as RedisConnectionError

from products.notifications.backend import pubsub
from products.notifications.backend.presentation.stream import notification_event_stream
from products.notifications.backend.pubsub import (
    NotificationSubscriptionError,
    publish_notification_payload,
    subscribe_to_notifications,
)


class TestNotificationStream:
    @pytest.fixture(autouse=True)
    def _publisher_not_paused(self):
        with patch.object(pubsub._publisher, "paused_until", 0.0):
            yield

    async def test_delivers_only_to_the_addressed_user_in_the_addressed_org(self) -> None:
        org_id, other_org_id = uuid.uuid4(), uuid.uuid4()
        stream = notification_event_stream(org_id, 42)
        try:
            assert await anext(stream) == b"event: ready\ndata: subscribed\n\n"
            async with (
                subscribe_to_notifications(org_id, 7) as other_user,
                subscribe_to_notifications(other_org_id, 42) as same_user_other_org,
            ):
                publish_notification_payload(org_id, {"id": "n1", "resolved_user_ids": [42]})
                publish_notification_payload(org_id, {"id": "n2", "resolved_user_ids": [7]})
                publish_notification_payload(other_org_id, {"id": "n3", "resolved_user_ids": [42]})

                assert await anext(stream) == b'data: {"id":"n1"}\n\n'
                assert await other_user.receive(5) == orjson.dumps({"id": "n2"})
                assert await same_user_other_org.receive(5) == orjson.dumps({"id": "n3"})
        finally:
            await stream.aclose()

    async def test_fails_open_subscriptions_when_the_redis_reader_fails(self) -> None:
        redis_pubsub = MagicMock()
        redis_pubsub.subscribe = AsyncMock()
        redis_pubsub.close = AsyncMock()
        redis_pubsub.get_message = AsyncMock(side_effect=RedisConnectionError("gone"))

        with patch("products.notifications.backend.pubsub.get_async_client") as async_client:
            async_client.return_value.pubsub.return_value = redis_pubsub
            async with subscribe_to_notifications(uuid.uuid4(), 42) as subscription:
                with pytest.raises(NotificationSubscriptionError):
                    await subscription.receive(5)

        redis_pubsub.close.assert_awaited()
