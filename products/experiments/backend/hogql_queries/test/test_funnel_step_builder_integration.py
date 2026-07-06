"""
Integration tests for FunnelStepBuilder with ExperimentQueryBuilder.

Tests that FunnelStepBuilder is correctly integrated into the query building pipeline
and produces the expected step columns in generated queries.
"""

from posthog.test.base import BaseTest

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode, ExperimentFunnelMetric

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.experiments.backend.hogql_queries.funnel_step_builder import FunnelStepBuilder


class TestFunnelStepBuilderIntegration(BaseTest):
    """Test FunnelStepBuilder integration with experiment queries."""

    def test_mixed_node_types_integration(self):
        """Test that FunnelStepBuilder handles mixed EventsNode and ActionsNode."""
        # Create an action first
        action = self.team.action_set.create(name="Test Action")

        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            ActionsNode(id=action.id),
            EventsNode(event="purchase"),
        ]

        builder = FunnelStepBuilder(series, self.team)
        exposure_filter = parse_expr("event = '$feature_flag_called'")

        # Should be able to generate boolean columns
        columns = builder.build_boolean_columns(exposure_filter)

        # Should have 4 columns: step_0 + 3 metric steps
        assert len(columns) == 4
        assert all(isinstance(col, ast.Alias) for col in columns)
        assert all(col.alias.startswith("step_") for col in columns)

    def test_datawarehouse_node_in_series_accepted_by_schema(self):
        """ExperimentFunnelMetric schema should accept ExperimentDataWarehouseNode in series."""
        # This tests the schema extension we made
        metric = ExperimentFunnelMetric(
            metric_type="funnel",
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ],
        )

        # Should not raise validation error
        assert len(metric.series) == 2
        assert isinstance(metric.series[0], EventsNode)
        assert isinstance(metric.series[1], ExperimentDataWarehouseNode)
