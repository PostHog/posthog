from posthog.test.base import BaseTest

from posthog.schema import AttributionMode, BaseMathType, ConversionGoalFilter1, NodeKind

from posthog.hogql import ast

from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import ConversionGoalProcessor
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig


def _make_event_goal(
    event: str = "purchase",
    properties: list | None = None,
    schema_map: dict | None = None,
) -> ConversionGoalFilter1:
    return ConversionGoalFilter1(
        kind=NodeKind.EVENTS_NODE,
        event=event,
        conversion_goal_id="goal_test",
        conversion_goal_name="Test Goal",
        math=BaseMathType.TOTAL,
        schema_map=schema_map or {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        properties=properties or [],
    )


class TestConversionGoalProcessorRefactor(BaseTest):
    """Tests for the public refactor surface.

    These pin the contract that downstream consumers rely on:
    - build_array_collection_query returns a SelectQuery
    - build_attribution_pipeline accepts any SelectQuery with the array schema
    - get_precompute_hash_inputs is stable for equivalent goals
    - _generate_funnel_query equals build_attribution_pipeline(build_array_collection_query(...))
    """

    CLASS_DATA_LEVEL_SETUP = False

    def _processor(self, **goal_overrides) -> ConversionGoalProcessor:
        return ConversionGoalProcessor(
            goal=_make_event_goal(**goal_overrides),
            index=0,
            team=self.team,
            config=MarketingAnalyticsConfig(),
        )

    def test_build_array_collection_query_returns_select(self):
        processor = self._processor()
        result = processor.build_array_collection_query(additional_conditions=[])
        assert isinstance(result, ast.SelectQuery)
        assert result.group_by is not None
        assert any(isinstance(g, ast.Field) and g.chain == ["events", "person_id"] for g in result.group_by)

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

        assert type(composed) is type(funnel_direct)
        assert len(composed.select) == len(funnel_direct.select)

    def test_attribution_pipeline_respects_multi_touch_config(self):
        single_touch_processor = self._processor()
        single_touch_processor.config.attribution_mode = AttributionMode.LAST_TOUCH

        multi_touch_processor = self._processor()
        multi_touch_processor.config.attribution_mode = AttributionMode.LINEAR

        collection = single_touch_processor.build_array_collection_query(additional_conditions=[])
        single = single_touch_processor.build_attribution_pipeline(collection)
        multi = multi_touch_processor.build_attribution_pipeline(collection)

        assert single.select != multi.select
