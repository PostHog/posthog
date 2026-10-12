import uuid
from collections.abc import Callable

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
from redis.exceptions import ConnectionError as RedisConnectionError

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.sync import database_sync_to_async

from products.access_control.backend.models.access_control import AccessControl
from products.notifications.backend import pubsub
from products.notifications.backend.presentation.stream import notification_event_stream
from products.notifications.backend.pubsub import (
    NotificationSubscriptionError,
    publish_notification_payload,
    subscribe_to_notifications,
)


def _member_of_new_project() -> tuple[Organization, Team, User]:
    organization = Organization.objects.create(name="Access Org")
    organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
    organization.save(update_fields=["available_product_features"])
    team = Team.objects.create(organization=organization, name="Access Project")
    return organization, team, User.objects.create_and_join(organization, "member@external.example.com", "password")


def _enforce_verified_domains(organization: Organization, team: Team, user: User) -> None:
    organization.enforce_verified_domains = True
    organization.save(update_fields=["enforce_verified_domains"])


def _deny_project_access(organization: Organization, team: Team, user: User) -> None:
    AccessControl.objects.create(
        team=team,
        resource="project",
        resource_id=str(team.id),
        organization_member=OrganizationMembership.objects.get(organization=organization, user=user),
        access_level="none",
    )


class TestNotificationStream:
    @pytest.fixture(autouse=True)
    def _publisher_not_paused(self):
        with patch.object(pubsub._publisher, "paused_until", 0.0):
            yield

    async def test_delivers_only_to_the_addressed_user_in_the_addressed_org(self) -> None:
        org_id, other_org_id = uuid.uuid4(), uuid.uuid4()
        async with (
            subscribe_to_notifications(org_id, 42) as user,
            subscribe_to_notifications(org_id, 7) as other_user,
            subscribe_to_notifications(other_org_id, 42) as same_user_other_org,
        ):
            publish_notification_payload(org_id, {"id": "n1", "resolved_user_ids": [42]})
            publish_notification_payload(org_id, {"id": "n2", "resolved_user_ids": [7]})
            publish_notification_payload(other_org_id, {"id": "n3", "resolved_user_ids": [42]})

            assert await user.receive(5) == orjson.dumps({"id": "n1"})
            assert await other_user.receive(5) == orjson.dumps({"id": "n2"})
            assert await same_user_other_org.receive(5) == orjson.dumps({"id": "n3"})

    @pytest.mark.parametrize("revoke_access", [_enforce_verified_domains, _deny_project_access])
    @pytest.mark.django_db(transaction=True)
    async def test_stream_stops_delivering_once_access_is_revoked(
        self, revoke_access: Callable[[Organization, Team, User], None]
    ) -> None:
        organization, team, user = await database_sync_to_async(_member_of_new_project, thread_sensitive=False)()
        stream = notification_event_stream(organization.id, user.id, domain_enforcement_exempt=False)
        try:
            assert await anext(stream) == b"event: ready\ndata: subscribed\n\n"
            publish_notification_payload(
                organization.id, {"id": "n1", "team_id": team.id, "resolved_user_ids": [user.id]}
            )
            assert await anext(stream) == b'data: {"id":"n1","team_id":%d}\n\n' % team.id

            await database_sync_to_async(revoke_access, thread_sensitive=False)(organization, team, user)
            publish_notification_payload(
                organization.id, {"id": "n2", "team_id": team.id, "resolved_user_ids": [user.id]}
            )
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
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
