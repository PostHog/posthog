from datetime import datetime

from posthog.test.base import BaseTest

from posthog.schema import EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast


class TestFunnelDWValidationIntegration(BaseTest):
    def test_query_builder_builds_union_query_for_dw_funnels(self):
        from posthog.schema import (
            ExperimentEventExposureConfig,
            ExperimentFunnelMetric,
            MultipleVariantHandling,
            StepOrderValue,
        )

        from posthog.hogql_queries.utils.query_date_range import QueryDateRange

        from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder

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

        query = builder.build_query()

        assert query is not None
        assert isinstance(query, ast.SelectQuery)

        assert query.ctes is not None
        assert "metric_events" in query.ctes

        # Note: We can't call to_printed_hogql() because it will try to resolve the DW table
        # which doesn't exist in the test environment. Instead, verify the CTE structure directly.
        metric_events_cte = query.ctes["metric_events"]
        assert isinstance(metric_events_cte, ast.CTE)

        assert metric_events_cte.expr is not None
