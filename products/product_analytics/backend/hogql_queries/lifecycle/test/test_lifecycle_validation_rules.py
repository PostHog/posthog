from unittest.mock import MagicMock

from django.test import SimpleTestCase, override_settings

from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, LifecycleDataWarehouseNode, LifecycleQuery

from posthog.hogql_queries.validation.validation import QueryValidationContext
from posthog.models import Team

from products.product_analytics.backend.hogql_queries.lifecycle.lifecycle_validation_rules import (
    RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget,
)


@override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True, CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
class TestLifecycleValidationRules(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team(id=1, timezone="UTC")

    def _context(self, query: LifecycleQuery) -> QueryValidationContext:
        runner = MagicMock(query=query, team=self.team, user=None)
        return QueryValidationContext(query=query, team=self.team, user=None, runner=runner)

    def _data_warehouse_series(self) -> list[LifecycleDataWarehouseNode]:
        return [
            LifecycleDataWarehouseNode(
                id="messages",
                table_name="messages",
                timestamp_field="sent_at",
                aggregation_target_field="person_id",
                created_at_field="signed_up_at",
            )
        ]

    def test_custom_aggregation_target_requires_data_warehouse_series(self):
        query = LifecycleQuery(
            customAggregationTarget=True,
            series=[EventsNode(event="$pageview")],
        )

        with self.assertRaises(ValidationError) as context:
            RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget().validate(self._context(query))

        self.assertIn(
            "Custom entity aggregation target is not supported for lifecycle insights without a data warehouse series.",
            str(context.exception),
        )
        self.assertEqual(
            context.exception.get_codes(),
            ["lifecycle_custom_aggregation_target_requires_data_warehouse_series"],
        )

    def test_custom_aggregation_target_allows_data_warehouse_series(self):
        query = LifecycleQuery(
            customAggregationTarget=True,
            series=self._data_warehouse_series(),
        )

        RequireLifecycleDataWarehouseSeriesForCustomAggregationTarget().validate(self._context(query))
