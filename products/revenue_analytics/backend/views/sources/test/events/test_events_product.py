from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.product import SCHEMA as PRODUCT_SCHEMA
from products.revenue_analytics.backend.views.sources.events.product import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestProductEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.events = self.setup_revenue_analytics_events()

    def test_build_product_queries_even_for_events_without_product_property(self):
        """Test building product queries even for events without productProperty configured."""
        # Test purchase event (no productProperty)
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

        # Test subscription_charge event (has productProperty)
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])
        query = build(handle)
        self.assertBuiltQueryStructure(
            query,
            self.SUBSCRIPTION_CHARGE_EVENT_NAME,
            "revenue_analytics.events.subscription_charge",
        )

        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required fields."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])

        query = build(handle)
        self.assertQueryContainsFields(query.query, PRODUCT_SCHEMA)
        self.assertQueryMatchesSnapshot(query.query.to_hogql(), replace_all_numbers=True)

    def test_product_fields_mapping(self):
        """Test that product-specific fields are properly mapped."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])

        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should map product_id from events properties
        self.assertIn("properties.product_id AS product_id", query_sql)

    def test_with_custom_product_property(self):
        """Test product query with custom productProperty name."""
        # Configure event with custom product property
        [event_config] = self.configure_events(
            [
                {
                    "eventName": "purchase",
                    "revenueProperty": "amount",
                    "productProperty": "item_id",  # Custom product property
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                }
            ]
        )

        handle = SourceHandle(type="events", team=self.team, event=event_config)
        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should use the custom property name
        self.assertIn("properties.item_id AS product_id", query_sql)

    def test_multiple_events_with_different_product_properties(self):
        """Test building product queries for multiple events with different productProperty names."""
        # Configure multiple events with different product properties
        [event_config1, event_config2] = self.configure_events(
            [
                {
                    "eventName": "purchase",
                    "revenueProperty": "amount",
                    "productProperty": "item_id",
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                },
                {
                    "eventName": "subscription_charge",
                    "revenueProperty": "price",
                    "productProperty": "service_id",
                    "currencyAwareDecimal": False,
                    "revenueCurrencyProperty": {"property": "currency"},
                },
            ]
        )

        # Verify each query uses the correct product property
        handle = SourceHandle(type="events", team=self.team, event=event_config1)
        query = build(handle)
        purchase_sql = query.query.to_hogql()
        self.assertIn("properties.item_id AS product_id", purchase_sql)

        handle = SourceHandle(type="events", team=self.team, event=event_config2)
        query = build(handle)
        subscription_sql = query.query.to_hogql()
        self.assertIn("properties.service_id AS product_id", subscription_sql)
