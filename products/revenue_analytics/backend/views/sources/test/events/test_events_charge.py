from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.charge import SCHEMA as CHARGE_SCHEMA
from products.revenue_analytics.backend.views.sources.events.charge import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestChargeEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.events = self.setup_revenue_analytics_events()

    def test_build_charge_queries_with_currency_aware_decimal(self):
        """Test building charge queries for events with currency-aware decimal handling."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)

        # Test first query (purchase event with currency-aware decimal)
        self.assertBuiltQueryStructure(query, "purchase", "revenue_analytics.events.purchase")

        # Print and snapshot the generated HogQL AST query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_charge_queries_without_currency_aware_decimal(self):
        """Test building charge queries for events without currency-aware decimal handling."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])

        query = build(handle)

        # Test second query (subscription_charge event without currency-aware decimal)
        self.assertBuiltQueryStructure(query, "subscription_charge", "revenue_analytics.events.subscription_charge")

        # Print and snapshot the generated HogQL AST query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required fields."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)

    def test_currency_aware_decimal_logic(self):
        """Test that currency-aware decimal logic is correctly applied."""

        # Purchase event has currencyAwareDecimal=True
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])
        purchase_query = build(handle)
        purchase_sql = purchase_query.query.to_hogql()

        # Should use is_zero_decimal_in_stripe check
        # by comparing against a list of zero-decimal currencies
        # List is omitted here for brevity
        self.assertIn("in(original_currency, [", purchase_sql)
        self.assertQueryMatchesSnapshot(purchase_sql, replace_all_numbers=True)

        # Subscription charge event has currencyAwareDecimal=False
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])
        subscription_query = build(handle)
        subscription_sql = subscription_query.query.to_hogql()

        # Should use constant True for enable_currency_aware_divider
        self.assertIn("true AS enable_currency_aware_divider", subscription_sql)
        self.assertQueryMatchesSnapshot(subscription_sql, replace_all_numbers=True)

    def test_with_team_base_currency(self):
        """Test that team base currency is properly used."""
        # Set a specific base currency for the team
        self.set_team_base_currency("EUR")

        handle = SourceHandle(type="events", team=self.team, event=self.events[0])
        query = build(handle)

        # Verify EUR is used as the base currency
        self.assertIn("'EUR' AS currency", query.query.to_hogql())
