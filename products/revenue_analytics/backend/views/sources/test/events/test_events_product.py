from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.product import SCHEMA as PRODUCT_SCHEMA
from products.revenue_analytics.backend.views.sources.events.product import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestProductEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_revenue_analytics_events()

    def test_build_product_queries_even_for_events_without_product_property(self):
        """Test building product queries even for events without productProperty configured."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Should build one query per configured event including the one without productProperty
        self.assertEqual(len(queries), 2)

        # Test subscription_charge event (has productProperty)
        key = self.SUBSCRIPTION_CHARGE_EVENT_NAME
        subscription_charge_query = next(query for query in queries if query.key == key)
        self.assertBuiltQueryStructure(
            subscription_charge_query,
            key,
            "revenue_analytics.events.subscription_charge",
        )

        query_sql = subscription_charge_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

        # Test purchase event (no productProperty)
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
        query = sorted(queries, key=lambda x: x.key)[1]

        self.assertQueryContainsFields(query.query, PRODUCT_SCHEMA)
        self.assertQueryMatchesSnapshot(query.query.to_hogql(), replace_all_numbers=True)

    def test_product_fields_mapping(self):
        """Test that product-specific fields are properly mapped."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))
        query = sorted(queries, key=lambda x: x.key)[1]
        query_sql = query.query.to_hogql()

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
