from datetime import UTC, datetime
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import AttributionMode, BaseMathType, ConversionGoalFilter1, EventPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.test.utils import pretty_print_in_tests

from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import ConversionGoalProcessor
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig


def _make_event_goal(
    event: str = "purchase",
    properties: list | None = None,
    schema_map: dict | None = None,
) -> ConversionGoalFilter1:
    return ConversionGoalFilter1(
        kind="EventsNode",
        event=event,
        conversion_goal_id="goal_test",
        conversion_goal_name="Test Goal",
        math=BaseMathType.TOTAL,
        schema_map=schema_map or {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        properties=properties or [],
    )


class TestConversionGoalProcessorRefactor(BaseTest):
    """Contract tests for the public attribution pipeline surface:
    - build_array_collection_query returns a SelectQuery grouped by person_id
    - build_attribution_pipeline accepts any SelectQuery with the array schema
    - composition pipeline(collection(...)) equals _generate_funnel_query(...)

    Snapshot tests pin the actual HogQL SQL of _generate_funnel_query so changes in the
    pipeline can be diffed against the prior baseline.
    """

    CLASS_DATA_LEVEL_SETUP = False
    snapshot: Any

    def _processor(self, **goal_overrides) -> ConversionGoalProcessor:
        return ConversionGoalProcessor(
            goal=_make_event_goal(**goal_overrides),
            index=0,
            team=self.team,
            config=MarketingAnalyticsConfig(),
        )

    def _print_sql(self, node: ast.SelectQuery) -> str:
        context = HogQLContext(team=self.team, enable_select_queries=True)
        sql, _ = prepare_and_print_ast(node, context=context, dialect="hogql")
        return pretty_print_in_tests(sql, self.team.pk)

    def test_build_array_collection_query_returns_select(self):
        processor = self._processor()
        result = processor.build_array_collection_query(additional_conditions=[])
        assert isinstance(result, ast.SelectQuery)
        assert result.group_by is not None
        assert any(isinstance(g, ast.Field) and g.chain == ["events", "person_id"] for g in result.group_by), (
            "array collection must group by events.person_id"
        )

    def test_build_attribution_pipeline_accepts_collection_output(self):
        processor = self._processor()
        collection = processor.build_array_collection_query(additional_conditions=[])
        result = processor.build_attribution_pipeline(collection)
        assert isinstance(result, ast.SelectQuery)

    def test_funnel_query_equals_pipeline_composition(self):
        processor = self._processor()
        funnel_direct = processor._generate_funnel_query(additional_conditions=[])

        collection = processor.build_array_collection_query(additional_conditions=[])
        composed = processor.build_attribution_pipeline(collection)

        assert self._print_sql(composed) == self._print_sql(funnel_direct)

    def test_attribution_pipeline_respects_multi_touch_config(self):
        single_touch_processor = self._processor()
        single_touch_processor.config.attribution_mode = AttributionMode.LAST_TOUCH

        multi_touch_processor = self._processor()
        multi_touch_processor.config.attribution_mode = AttributionMode.LINEAR

        collection = single_touch_processor.build_array_collection_query(additional_conditions=[])
        single = single_touch_processor.build_attribution_pipeline(collection)
        multi = multi_touch_processor.build_attribution_pipeline(collection)

        assert single.select != multi.select

    def test_precompute_skipped_when_tracked_property_restricted(self):
        # Precompute materializes tracked attribution properties via the touchpoints table, bypassing
        # the per-user masking HogQL applies to events.properties. When such a property is restricted
        # for the user, eligibility must fail so the direct (masked) events query is used instead.
        processor = self._processor()
        processor.config.conversion_goal_precomputation_enabled = True
        date_from = datetime(2025, 1, 1, tzinfo=UTC)
        date_to = datetime(2025, 1, 31, tzinfo=UTC)
        target = (
            "products.marketing_analytics.backend.hogql_queries.conversion_goal_processor.get_restricted_property_names"
        )

        with patch(target, return_value=set()):
            assert processor._should_use_precompute(date_from, date_to) is True

        # utm_source is one of the tracked attribution properties resolved from the goal's schema_map.
        with patch(target, return_value={"utm_source"}):
            assert processor._should_use_precompute(date_from, date_to) is False

    def test_tracked_fields_match_touchpoints_table_schema(self):
        from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import (
            MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES,
        )

        from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import TRACKED_FIELDS

        assert [f.name for f in TRACKED_FIELDS] == MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES

    @parameterized.expand(
        [
            (AttributionMode.FIRST_TOUCH,),
            (AttributionMode.LAST_TOUCH,),
            (AttributionMode.LINEAR,),
            (AttributionMode.TIME_DECAY,),
            (AttributionMode.POSITION_BASED,),
        ]
    )
    def test_attribution_pipeline_differs_from_last_touch(self, mode: AttributionMode):
        """LAST_TOUCH is the baseline; every other mode must produce a different pipeline SQL."""
        baseline = self._processor()
        baseline.config.attribution_mode = AttributionMode.LAST_TOUCH

        variant = self._processor()
        variant.config.attribution_mode = mode

        collection = baseline.build_array_collection_query(additional_conditions=[])
        baseline_sql = self._print_sql(baseline.build_attribution_pipeline(collection))
        variant_sql = self._print_sql(variant.build_attribution_pipeline(collection))

        if mode == AttributionMode.LAST_TOUCH:
            assert baseline_sql == variant_sql
        else:
            assert baseline_sql != variant_sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_funnel_query_single_touch_default(self):
        processor = self._processor()
        query = processor._generate_funnel_query(additional_conditions=[])
        assert self._print_sql(query) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_funnel_query_multi_touch_linear(self):
        processor = self._processor()
        processor.config.attribution_mode = AttributionMode.LINEAR
        query = processor._generate_funnel_query(additional_conditions=[])
        assert self._print_sql(query) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_snapshot_funnel_query_with_property_filter(self):
        processor = self._processor(
            properties=[
                EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT, type="event"),
            ],
        )
        additional_conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDate", args=[ast.Constant(value="2023-01-01")]),
            ),
        ]
        query = processor._generate_funnel_query(additional_conditions=additional_conditions)
        assert self._print_sql(query) == self.snapshot
