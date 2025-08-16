from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.sources.events.product import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest
from products.revenue_analytics.backend.views.schemas.product import SCHEMA as PRODUCT_SCHEMA


class TestProductEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_revenue_analytics_events()

    def test_build_product_queries_only_for_events_with_product_property(self):
        """Test building product queries only for events with productProperty configured."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Should build one query per configured event that has productProperty
        # Only subscription_charge has productProperty in our default config
        self.assertEqual(len(queries), 1)

        # Test subscription_charge event (has productProperty)
        subscription_query = queries[0]
        self.assertBuiltQueryStructure(
            subscription_query, "subscription_charge", "revenue_analytics.events.subscription_charge"
        )

        # Print and snapshot the generated HogQL AST query
        query_sql = subscription_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_product_property_events(self):
        """Test that build skips events without productProperty."""
        # Configure events without productProperty
        self.configure_events(
            [
                {
                    "eventName": "purchase",
                    "revenueProperty": "amount",
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                    # No productProperty
                }
            ]
        )

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        # Should return empty since no events have productProperty
        self.assertEqual(len(queries), 0)

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
        subscription_query = queries[0]

        self.assertQueryContainsFields(subscription_query.query, PRODUCT_SCHEMA)
        self.assertQueryMatchesSnapshot(subscription_query.query.to_hogql(), replace_all_numbers=True)

    def test_product_fields_mapping(self):
        """Test that product-specific fields are properly mapped."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))
        subscription_query = queries[0]
        query_sql = subscription_query.query.to_hogql()

        # Should map product_id from events properties
        self.assertIn("properties.product_id AS product_id", query_sql)

    def test_with_custom_product_property(self):
        """Test product query with custom productProperty name."""
        # Configure event with custom product property
        self.configure_events(
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

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        self.assertEqual(len(queries), 1)

        purchase_query = queries[0]
        query_sql = purchase_query.query.to_hogql()

        # Should use the custom property name
        self.assertIn("properties.item_id AS product_id", query_sql)

    def test_multiple_events_with_different_product_properties(self):
        """Test building product queries for multiple events with different productProperty names."""
        # Configure multiple events with different product properties
        self.configure_events(
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

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        # Should build queries for both events
        self.assertEqual(len(queries), 2)

        # Verify each query uses the correct product property
        purchase_query = queries[0]
        purchase_sql = purchase_query.query.to_hogql()
        self.assertIn("properties.item_id AS product_id", purchase_sql)

        subscription_query = queries[1]
        subscription_sql = subscription_query.query.to_hogql()
        self.assertIn("properties.service_id AS product_id", subscription_sql)
