from freezegun import freeze_time

from products.revenue_analytics.backend.views.schemas.mrr import SCHEMA as MRR_SCHEMA
from products.revenue_analytics.backend.views.sources.stripe.mrr import build
from products.revenue_analytics.backend.views.sources.test.stripe.base import StripeSourceBaseTest
import pytest


class TestMRRStripeBuilder(StripeSourceBaseTest):
    QUERY_TIMESTAMP = "2025-05-30"

    def setUp(self):
        super().setUp()
        self.setup_stripe_external_data_source()

    def test_build_mrr_query(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = build(self.stripe_handle)

            expected_key = f"{self.external_data_source.id}-mrr"
            expected_prefix = f"stripe.{self.external_data_source.prefix}"
            self.assertBuiltQueryStructure(query, expected_key, expected_prefix)

            query_sql = query.query.to_hogql()
            self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_query_structure_contains_required_fields(self):
        query = build(self.stripe_handle)
        self.assertQueryContainsFields(query.query, MRR_SCHEMA)

    def test_mrr_uses_argmax_for_latest_amount(self):
        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        assert "argMax(amount, timestamp)" in query_sql

    def test_mrr_filters_for_recurring_only(self):
        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        assert "and(is_recurring," in query_sql

    def test_mrr_groups_by_customer_and_subscription(self):
        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        assert "GROUP BY source_label, customer_id, subscription_id" in query_sql

    def test_mrr_unions_revenue_item_and_subscription_queries(self):
        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        assert "UNION ALL" in query_sql

    def test_subscription_end_events_have_zero_amount(self):
        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        assert "toDecimal(0," in query_sql

    def test_mrr_references_correct_base_views(self):
        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        expected_prefix = f"stripe.{self.external_data_source.prefix}"
        assert f"`{expected_prefix}.revenue_item_revenue_view`" in query_sql
        assert f"`{expected_prefix}.subscription_revenue_view`" in query_sql

    def test_build_requires_source(self):
        handle = self.create_stripe_handle_without_source()

        with pytest.raises(ValueError) as context:
            build(handle)

        assert "Source is required" in str(context.value)
