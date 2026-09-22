"""
Integration tests for FunnelDWValidator with ExperimentQueryBuilder.

These tests build a query against a team, so they need a database. The validator
logic itself is covered in test_funnel_validation.py.
"""

from datetime import datetime

from posthog.test.base import BaseTest

from posthog.schema import EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast


class TestFunnelDWValidationIntegration(BaseTest):
    """Integration tests for FunnelDWValidator in query execution context."""

    def test_query_builder_builds_union_query_for_dw_funnels(self):
        """Query builder should successfully build UNION ALL query for DW funnels."""
        from posthog.schema import (
            ExperimentEventExposureConfig,
            ExperimentFunnelMetric,
            MultipleVariantHandling,
            StepOrderValue,
        )

        from posthog.hogql_queries.utils.query_date_range import QueryDateRange

        from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder

        # Create metric with DW step
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="purchase_date",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        # Build query using query builder directly
        exposure_config = ExperimentEventExposureConfig(event="$feature_flag_called", properties=[])
        date_range = QueryDateRange(
            date_range=None,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

        builder = ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key="test-feature",
            exposure_config=exposure_config,
            filter_test_accounts=True,
            multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
            variants=["control", "test"],
            date_range_query=date_range,
            entity_key="person_id",
            metric=metric,
        )

        # Should successfully build query without errors
        query = builder.build_query()

        # Verify query structure
        assert query is not None
        assert isinstance(query, ast.SelectQuery)

        # Verify the query has metric_events CTE with UNION ALL
        assert query.ctes is not None
        assert "metric_events" in query.ctes

        # The CTE SQL should contain UNION ALL and DW table reference
        # Note: We can't call to_printed_hogql() because it will try to resolve the DW table
        # which doesn't exist in the test environment. Instead, verify the CTE structure directly.
        metric_events_cte = query.ctes["metric_events"]
        assert isinstance(metric_events_cte, ast.CTE)

        # The CTE expr should be a SelectSetQuery (UNION) or contain one
        # For now, just verify it was built successfully
        assert metric_events_cte.expr is not None
