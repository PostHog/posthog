from typing import cast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle
from products.revenue_analytics.backend.views.schemas.subscription import SCHEMA as SUBSCRIPTION_SCHEMA
from products.revenue_analytics.backend.views.sources.events.subscription import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestSubscriptionEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.events = self.setup_revenue_analytics_events()

    def test_build_subscription_queries_even_for_events_without_subscription_property(self):
        """Test building subscription queries even for events without subscriptionProperty configured."""

        # Test purchase event (no subscriptionProperty)
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])
        query = build(handle)
        self.assertBuiltQueryStructure(
            query,
            self.PURCHASE_EVENT_NAME,
            "revenue_analytics.events.purchase",
            expected_test_comments="no_property",
        )

        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

        # Test subscription_charge event (has subscriptionProperty)
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])
        query = build(handle)
        self.assertBuiltQueryStructure(
            cast(BuiltQuery, query),
            self.SUBSCRIPTION_CHARGE_EVENT_NAME,
            "revenue_analytics.events.subscription_charge",
        )

        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required fields."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        self.assertQueryContainsFields(query.query, SUBSCRIPTION_SCHEMA)
        self.assertQueryMatchesSnapshot(query.query.to_hogql(), replace_all_numbers=True)

    def test_subscription_fields_mapping(self):
        """Test that subscription-specific fields are properly mapped."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])
        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should map subscription_id from events properties
        assert "properties.subscription_id AS subscription_id" in query_sql

        # Should use subscription_id as id
        assert "subscription_id AS id" in query_sql

        # Should set null values for fields not available from events
        assert "NULL AS plan_id" in query_sql
        assert "NULL AS status" in query_sql
        assert "NULL AS metadata" in query_sql

    def test_with_custom_subscription_property(self):
        """Test subscription query with custom subscriptionProperty name."""
        # Configure event with custom subscription property
        [event_config] = self.configure_events(
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

        handle = SourceHandle(type="events", team=self.team, event=event_config)
        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should use the custom property names
        assert "properties.sub_id AS subscription_id" in query_sql
        assert "min(properties.product) AS product_id" in query_sql

    def test_subscription_without_product_property(self):
        """Test subscription query when event has no productProperty."""
        # Configure event without productProperty
        [event_config] = self.configure_events(
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

        handle = SourceHandle(type="events", team=self.team, event=event_config)
        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should default product_id to null when no productProperty
        assert "NULL AS product_id" in query_sql

    def test_multiple_events_with_different_subscription_properties(self):
        """Test building subscription queries for multiple events with different subscriptionProperty names."""
        # Configure multiple events with different subscription properties
        [event_config1, event_config2] = self.configure_events(
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

        # Verify each query uses the correct subscription property
        handle = SourceHandle(type="events", team=self.team, event=event_config1)
        query = build(handle)
        created_sql = query.query.to_hogql()
        assert "properties.sub_id AS subscription_id" in created_sql
        assert "min(properties.plan_id) AS product_id" in created_sql

        handle = SourceHandle(type="events", team=self.team, event=event_config2)
        query = build(handle)
        renewed_sql = query.query.to_hogql()
        assert "properties.subscription_uuid AS subscription_id" in renewed_sql
        assert "min(properties.service_name) AS product_id" in renewed_sql
