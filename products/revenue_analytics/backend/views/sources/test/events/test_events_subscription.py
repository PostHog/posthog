from typing import cast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle
from products.revenue_analytics.backend.views.schemas.subscription import SCHEMA as SUBSCRIPTION_SCHEMA
from products.revenue_analytics.backend.views.sources.events.subscription import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestSubscriptionEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_revenue_analytics_events()

    def test_build_subscription_queries_even_for_events_without_subscription_property(self):
        """Test building subscription queries even for events without subscriptionProperty configured."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Should build one query per configured event including the one without subscriptionProperty
        self.assertEqual(len(queries), 2)

        # Test subscription_charge event (has subscriptionProperty)
        key = self.SUBSCRIPTION_CHARGE_EVENT_NAME
        subscription_charge_query = next(query for query in queries if query.key == key)
        self.assertBuiltQueryStructure(
            cast(BuiltQuery, subscription_charge_query),
            key,
            "revenue_analytics.events.subscription_charge",
        )

        query_sql = subscription_charge_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

        # Test purchase event (no subscriptionProperty)
        key = f"{self.PURCHASE_EVENT_NAME}.no_property"
        purchase_query = next(query for query in queries if query.key == key)
        self.assertBuiltQueryStructure(purchase_query, key, "revenue_analytics.events.purchase")

        query_sql = purchase_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_events_configured(self):
        """Test that build returns empty list when no events are configured."""
        # Clear revenue analytics events
        self.clear_events()

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        self.assertEqual(len(queries), 0)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required fields."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))
        subscription_query = sorted(queries, key=lambda x: x.key)[1]

        self.assertQueryContainsFields(subscription_query.query, SUBSCRIPTION_SCHEMA)
        self.assertQueryMatchesSnapshot(subscription_query.query.to_hogql(), replace_all_numbers=True)

    def test_subscription_fields_mapping(self):
        """Test that subscription-specific fields are properly mapped."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))
        subscription_query = sorted(queries, key=lambda x: x.key)[1]
        query_sql = subscription_query.query.to_hogql()

        # Should map subscription_id from events properties
        self.assertIn("properties.subscription_id AS subscription_id", query_sql)

        # Should use subscription_id as id
        self.assertIn("subscription_id AS id", query_sql)

        # Should set null values for fields not available from events
        self.assertIn("NULL AS plan_id", query_sql)
        self.assertIn("NULL AS status", query_sql)
        self.assertIn("NULL AS metadata", query_sql)

    def test_with_custom_subscription_property(self):
        """Test subscription query with custom subscriptionProperty name."""
        # Configure event with custom subscription property
        self.configure_events(
            [
                {
                    "eventName": "subscription_event",
                    "revenueProperty": "amount",
                    "subscriptionProperty": "sub_id",  # Custom subscription property
                    "productProperty": "product",
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                }
            ]
        )

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        self.assertEqual(len(queries), 1)

        subscription_query = queries[0]
        query_sql = subscription_query.query.to_hogql()

        # Should use the custom property names
        self.assertIn("properties.sub_id AS subscription_id", query_sql)
        self.assertIn("min(properties.product) AS product_id", query_sql)

    def test_subscription_without_product_property(self):
        """Test subscription query when event has no productProperty."""
        # Configure event without productProperty
        self.configure_events(
            [
                {
                    "eventName": "subscription_event",
                    "revenueProperty": "amount",
                    "subscriptionProperty": "subscription_id",
                    # No productProperty
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                }
            ]
        )

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        subscription_query = queries[0]
        query_sql = subscription_query.query.to_hogql()

        # Should default product_id to null when no productProperty
        self.assertIn("NULL AS product_id", query_sql)

    def test_multiple_events_with_different_subscription_properties(self):
        """Test building subscription queries for multiple events with different subscriptionProperty names."""
        # Configure multiple events with different subscription properties
        self.configure_events(
            [
                {
                    "eventName": "subscription_created",
                    "revenueProperty": "amount",
                    "subscriptionProperty": "sub_id",
                    "productProperty": "plan_id",
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                },
                {
                    "eventName": "subscription_renewed",
                    "revenueProperty": "price",
                    "subscriptionProperty": "subscription_uuid",
                    "productProperty": "service_name",
                    "currencyAwareDecimal": False,
                    "revenueCurrencyProperty": {"property": "currency"},
                },
            ]
        )

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        # Should build queries for both events
        self.assertEqual(len(queries), 2)

        # Verify each query uses the correct subscription property
        created_query = queries[0]
        created_sql = created_query.query.to_hogql()
        self.assertIn("properties.sub_id AS subscription_id", created_sql)
        self.assertIn("min(properties.plan_id) AS product_id", created_sql)

        renewed_query = queries[1]
        renewed_sql = renewed_query.query.to_hogql()
        self.assertIn("properties.subscription_uuid AS subscription_id", renewed_sql)
        self.assertIn("min(properties.service_name) AS product_id", renewed_sql)
