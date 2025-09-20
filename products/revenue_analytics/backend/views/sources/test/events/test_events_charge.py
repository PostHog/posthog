from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.charge import SCHEMA as CHARGE_SCHEMA
from products.revenue_analytics.backend.views.sources.events.charge import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestChargeEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_revenue_analytics_events()

    def test_build_charge_queries_with_currency_aware_decimal(self):
        """Test building charge queries for events with currency-aware decimal handling."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Should build one query per configured event
        self.assertEqual(len(queries), 2)

        # Test first query (purchase event with currency-aware decimal)
        purchase_query = queries[0]
        self.assertBuiltQueryStructure(purchase_query, "purchase", "revenue_analytics.events.purchase")

        # Print and snapshot the generated HogQL AST query
        query_sql = purchase_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_charge_queries_without_currency_aware_decimal(self):
        """Test building charge queries for events without currency-aware decimal handling."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Test second query (subscription_charge event without currency-aware decimal)
        subscription_query = queries[1]
        self.assertBuiltQueryStructure(
            subscription_query, "subscription_charge", "revenue_analytics.events.subscription_charge"
        )

        # Print and snapshot the generated HogQL AST query
        query_sql = subscription_query.query.to_hogql()
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
        purchase_query = queries[0]

        self.assertQueryContainsFields(purchase_query.query, CHARGE_SCHEMA)

    def test_currency_aware_decimal_logic(self):
        """Test that currency-aware decimal logic is correctly applied."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Purchase event has currencyAwareDecimal=True
        purchase_query = queries[0]
        purchase_sql = purchase_query.query.to_hogql()

        # Should use is_zero_decimal_in_stripe check
        # by comparing against a list of zero-decimal currencies
        # List is omitted here for brevity
        self.assertIn("in(original_currency, [", purchase_sql)
        self.assertQueryMatchesSnapshot(purchase_sql, replace_all_numbers=True)

        # Subscription charge event has currencyAwareDecimal=False
        subscription_query = queries[1]
        subscription_sql = subscription_query.query.to_hogql()

        # Should use constant True for enable_currency_aware_divider
        self.assertIn("true AS enable_currency_aware_divider", subscription_sql)
        self.assertQueryMatchesSnapshot(subscription_sql, replace_all_numbers=True)

    def test_with_team_base_currency(self):
        """Test that team base currency is properly used."""
        # Set a specific base currency for the team
        self.set_team_base_currency("EUR")

        handle = SourceHandle(type="events", team=self.team)
        queries = list(build(handle))

        purchase_query = queries[0]
        query_sql = purchase_query.query.to_hogql()

        # Verify EUR is used as the base currency
        self.assertIn("'EUR' AS currency", query_sql)
