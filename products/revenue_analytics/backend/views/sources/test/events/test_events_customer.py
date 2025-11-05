from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA as CUSTOMER_SCHEMA
from products.revenue_analytics.backend.views.sources.events.customer import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestCustomerEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.events = self.setup_revenue_analytics_events()

    def test_build_customer_queries_for_all_events(self):
        """Test building customer queries for all configured events."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)

        # Test first query (purchase event)
        self.assertBuiltQueryStructure(query, "purchase", "revenue_analytics.events.purchase")

        # Print and snapshot the generated HogQL AST query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_customer_query_uses_distinct_persons(self):
        """Test that customer queries use DISTINCT to get unique persons."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[1])

        query = build(handle)

        # Test subscription_charge query
        self.assertBuiltQueryStructure(query, "subscription_charge", "revenue_analytics.events.subscription_charge")

        # Should use DISTINCT in the events subquery to get unique persons
        query_sql = query.query.to_hogql()
        self.assertIn("SELECT DISTINCT", query_sql)
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required fields."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)

    def test_customer_query_structure(self):
        """Test that customer queries have the expected structure."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        # Customer queries should join persons with events
        query = build(handle)
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)
