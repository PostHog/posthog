from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.revenue_item import SCHEMA as REVENUE_ITEM_SCHEMA
from products.revenue_analytics.backend.views.sources.events.revenue_item import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestRevenueItemEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.events = self.setup_revenue_analytics_events()

    def test_build_revenue_item_queries_with_currency_aware_decimal(self):
        """Test building revenue item queries for events with currency-aware decimal handling."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        # Test first query (purchase event with currency-aware decimal)
        query = build(handle)
        self.assertBuiltQueryStructure(query, "purchase", "revenue_analytics.events.purchase")

        # Print and snapshot the generated HogQL AST query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_revenue_item_queries_without_currency_aware_decimal(self):
        """Test building revenue item queries for events without currency-aware decimal handling."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])

        # Test second query (subscription_charge event without currency-aware decimal)
        query = build(handle)
        self.assertBuiltQueryStructure(query, "subscription_charge", "revenue_analytics.events.subscription_charge")

        # Print and snapshot the generated HogQL AST query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required fields."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        self.assertQueryContainsFields(query.query, REVENUE_ITEM_SCHEMA)

    def test_currency_aware_decimal_logic(self):
        """Test that currency-aware decimal logic is correctly applied."""

        # Purchase event has currencyAwareDecimal=True
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])
        query = build(handle)
        purchase_sql = query.query.to_hogql()

        # Should use is_zero_decimal_in_stripe check
        # by comparing against a list of zero-decimal currencies
        self.assertIn("in(original_currency, [", purchase_sql)
        self.assertQueryMatchesSnapshot(purchase_sql, replace_all_numbers=True)

        # Subscription charge event has currencyAwareDecimal=False
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])
        query = build(handle)
        subscription_sql = query.query.to_hogql()

        # Should use constant True for enable_currency_aware_divider
        self.assertIn("true AS enable_currency_aware_divider", subscription_sql)
        self.assertQueryMatchesSnapshot(subscription_sql, replace_all_numbers=True)

    def test_revenue_item_specific_fields(self):
        """Test that revenue item specific fields are properly handled."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])

        query = build(handle)

        # Test subscription_charge query (has product and subscription properties)
        query_sql = query.query.to_hogql()

        # Should include is_recurring based on subscription property
        self.assertIn("isNotNull(properties.subscription_id) AS is_recurring", query_sql)

        # Should include product_id from productProperty
        self.assertIn("properties.product_id AS product_id", query_sql)

        # Should include subscription_id from subscriptionProperty
        self.assertIn("properties.subscription_id AS subscription_id", query_sql)

    def test_with_team_base_currency(self):
        """Test that team base currency is properly used."""
        # Set a specific base currency for the team
        self.set_team_base_currency("EUR")

        handle = SourceHandle(type="events", team=self.team, event=self.events[0])
        query = build(handle)
        query_sql = query.query.to_hogql()

        # Verify EUR is used as the base currency
        self.assertIn("'EUR' AS currency", query_sql)

    def test_is_recurring_logic(self):
        """Test that is_recurring field logic works correctly."""
        # Test event without subscription property
        [event_config] = self.configure_events(
            [
                {
                    "eventName": "purchase",
                    "revenueProperty": "amount",
                    "currencyAwareDecimal": True,
                    "revenueCurrencyProperty": {"static": "USD"},
                    # No subscriptionProperty
                }
            ]
        )

        handle = SourceHandle(type="events", team=self.team, event=event_config)
        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should be hardcoded to false when no subscription property
        self.assertIn("false AS is_recurring", query_sql)
