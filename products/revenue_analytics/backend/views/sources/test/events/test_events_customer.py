from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA as CUSTOMER_SCHEMA
from products.revenue_analytics.backend.views.sources.events.customer import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestCustomerEventsBuilder(EventsSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_revenue_analytics_events()

    def test_build_customer_queries_for_all_events(self):
        """Test building customer queries for all configured events."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Should build one query per configured event
        self.assertEqual(len(queries), 2)

        # Test first query (purchase event)
        purchase_query = queries[0]
        self.assertBuiltQueryStructure(purchase_query, "purchase", "revenue_analytics.events.purchase")

        # Print and snapshot the generated HogQL AST query
        query_sql = purchase_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_customer_query_uses_distinct_persons(self):
        """Test that customer queries use DISTINCT to get unique persons."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Test subscription_charge query
        subscription_query = queries[1]
        self.assertBuiltQueryStructure(
            subscription_query, "subscription_charge", "revenue_analytics.events.subscription_charge"
        )

        # Should use DISTINCT in the events subquery to get unique persons
        query_sql = subscription_query.query.to_hogql()
        self.assertIn("SELECT DISTINCT", query_sql)
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

        self.assertQueryContainsFields(purchase_query.query, CUSTOMER_SCHEMA)

    def test_customer_query_structure(self):
        """Test that customer queries have the expected structure."""
        handle = SourceHandle(type="events", team=self.team)

        queries = list(build(handle))

        # Customer queries should join persons with events
        purchase_query = queries[0]
        query_sql = purchase_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)
