from datetime import timedelta
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from posthog.clickhouse.query_tagging import tags_context
from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.event.util import create_event

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.mcp_events.backend.facade import api
from products.mcp_events.backend.models import MCPEventSubscription


class TestMCPEventPreview(ClickhouseTestMixin, APIBaseTest):
    def test_preview_filters_limits_orders_and_redacts_without_creating_subscription(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        for name in ("plan", "$groups.organization"):
            definition = PropertyDefinition.objects.create(
                team=self.team, name=name, property_type="String", type=PropertyDefinition.Type.EVENT
            )
            PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        self.enterContext(
            patch(
                "products.mcp_events.backend.logic.properties.get_group_types_for_project",
                return_value=[{"group_type_index": 0, "group_type": "organization"}],
            )
        )
        now = timezone.now()
        matching_ids = [UUID(int=index + 1) for index in range(7)]
        rows = [
            (event_id, "example_event", 2, now - timedelta(minutes=index + 1))
            for index, event_id in enumerate(matching_ids)
        ]
        rows.extend(
            [
                (UUID(int=100), "example_event", 5, now),
                (UUID(int=101), "other_event", 2, now),
                (UUID(int=102), "example_event", 2, now - timedelta(days=8)),
            ]
        )
        for event_uuid, event, rating, timestamp in rows:
            create_event(
                event_uuid=event_uuid,
                event=event,
                team=self.team,
                distinct_id="sample-user",
                timestamp=timestamp,
                properties={
                    "rating": rating,
                    "plan": "enterprise",
                    "$groups": {"organization": "hidden"},
                    "$group_0": "hidden",
                },
            )
        with (
            tags_context(product=None, feature=None),
            patch("posthog.clickhouse.client.execute.DEBUG", True),
            patch("posthog.clickhouse.client.execute.TEST", False),
        ):
            result = api.preview(
                team_id=self.team.pk,
                user_id=self.user.pk,
                filters={
                    "events": [{"id": "example_event", "type": "events"}],
                    "properties": [{"key": "rating", "type": "event", "operator": "lt", "value": 3}],
                },
            )
        self.assertEqual(
            [example.eventId for example in result.examples], [str(event_id) for event_id in matching_ids[:5]]
        )
        for example in result.examples:
            self.assertEqual(example.data.properties, {"rating": 2, "$groups": {}})
            self.assertIsNone(example.cursor)
        self.assertEqual((result.sample_limit, result.lookback_days), (5, 7))
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
