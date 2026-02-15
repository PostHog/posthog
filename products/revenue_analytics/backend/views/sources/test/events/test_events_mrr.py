from freezegun import freeze_time

from products.revenue_analytics.backend.views.core import SourceHandle
from products.revenue_analytics.backend.views.schemas.mrr import SCHEMA as MRR_SCHEMA
from products.revenue_analytics.backend.views.sources.events.mrr import build
from products.revenue_analytics.backend.views.sources.test.events.base import EventsSourceBaseTest


class TestMRREventsBuilder(EventsSourceBaseTest):
    QUERY_TIMESTAMP = "2025-05-30"

    def setUp(self):
        super().setUp()
        self.events = self.setup_revenue_analytics_events()

    def test_build_mrr_query(self):
        """Test building MRR query for an event."""
        with freeze_time(self.QUERY_TIMESTAMP):
            handle = SourceHandle(type="events", team=self.team, event=self.events[0])

            query = build(handle)

            self.assertBuiltQueryStructure(query, self.PURCHASE_EVENT_NAME, "revenue_analytics.events.purchase")
            query_sql = query.query.to_hogql()
            self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        """Test that the generated query contains all required MRR fields."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        self.assertQueryContainsFields(query.query, MRR_SCHEMA)

    def test_mrr_uses_argmax_for_latest_amount(self):
        """Test that MRR calculation uses argMax to get the latest amount per subscription."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should use argMax to get the latest amount by timestamp
        self.assertIn("argMax(amount, timestamp)", query_sql)

    def test_mrr_filters_for_recurring_only(self):
        """Test that MRR query only includes recurring revenue items."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should filter for is_recurring
        self.assertIn("and(is_recurring,", query_sql)

    def test_mrr_groups_by_customer_and_subscription(self):
        """Test that MRR query groups by source_label, customer_id, and subscription_id."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should group by source_label, customer_id, subscription_id
        self.assertIn("GROUP BY source_label, customer_id, subscription_id", query_sql)

    def test_mrr_unions_revenue_item_and_subscription_queries(self):
        """Test that MRR query unions revenue items with subscription end events."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        query_sql = query.query.to_hogql()

        # Should use UNION ALL to combine revenue items and subscription end events
        self.assertIn("UNION ALL", query_sql)

    def test_subscription_end_events_have_zero_amount(self):
        """Test that subscription end events contribute a zero amount to MRR."""
        handle = SourceHandle(type="events", team=self.team, event=self.events[0])

        query = build(handle)
        query_sql = query.query.to_hogql()

        # Subscription end events should have toDecimal(0, ...) as amount
        self.assertIn("toDecimal(0,", query_sql)

    def test_build_requires_event(self):
        """Test that build raises ValueError when event is None."""
        handle = SourceHandle(type="events", team=self.team, event=None)

        with self.assertRaises(ValueError) as context:
            build(handle)

        self.assertIn("Event is required", str(context.exception))
