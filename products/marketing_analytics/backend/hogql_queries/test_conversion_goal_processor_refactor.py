from datetime import UTC, datetime
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    AttributionMode,
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter3,
    EventPropertyFilter,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, to_printed_hogql
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


def _make_data_warehouse_goal() -> ConversionGoalFilter3:
    return ConversionGoalFilter3(
        kind="DataWarehouseNode",
        id="stripe_charges",
        id_field="id",
        table_name="stripe_charges",
        distinct_id_field="customer_email",
        timestamp_field="created_at",
        conversion_goal_id="goal_dw",
        conversion_goal_name="Test DW Goal",
        schema_map={"utm_campaign_name": "utm_campaign"},
    )


class TestConversionGoalProcessorRefactor(BaseTest):
    """Tests for the public refactor surface.

    Contract tests pin the shape of the new public API:
    - build_array_collection_query returns a SelectQuery grouped by person_id
    - build_attribution_pipeline accepts any SelectQuery with the array schema
    - composition pipeline(collection(...)) equals _generate_funnel_query(...)

    Snapshot tests pin the actual HogQL SQL of _generate_funnel_query so the
    refactor can be diffed against the pre-refactor baseline: revert the
    processor file to master, regenerate snapshots, stage them, re-apply the
    refactor, regenerate again, and read the git diff on the .ambr file.
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

    def test_hash_inputs_stable_for_identical_goals(self):
        a = self._processor()
        b = self._processor()
        assert a.get_precompute_hash_inputs() == b.get_precompute_hash_inputs()

    def test_hash_inputs_differ_for_different_event(self):
        a = self._processor(event="purchase")
        b = self._processor(event="signup")
        assert a.get_precompute_hash_inputs() != b.get_precompute_hash_inputs()

    def test_hash_inputs_differ_for_different_attribution_window(self):
        a = self._processor()
        a.config.attribution_window_days = 30
        b = self._processor()
        b.config.attribution_window_days = 90
        assert a.get_precompute_hash_inputs() != b.get_precompute_hash_inputs()

    def test_hash_inputs_includes_team_id(self):
        processor = self._processor()
        assert processor.get_precompute_hash_inputs()["team_id"] == self.team.pk

    def test_hash_inputs_serializable(self):
        import json

        processor = self._processor()
        json.dumps(processor.get_precompute_hash_inputs(), default=str, sort_keys=True)

    def test_attribution_pipeline_respects_multi_touch_config(self):
        single_touch_processor = self._processor()
        single_touch_processor.config.attribution_mode = AttributionMode.LAST_TOUCH

        multi_touch_processor = self._processor()
        multi_touch_processor.config.attribution_mode = AttributionMode.LINEAR

        collection = single_touch_processor.build_array_collection_query(additional_conditions=[])
        single = single_touch_processor.build_attribution_pipeline(collection)
        multi = multi_touch_processor.build_attribution_pipeline(collection)

        assert single.select != multi.select

    def test_hash_inputs_depend_on_attribution_mode(self):
        first = self._processor()
        first.config.attribution_mode = AttributionMode.FIRST_TOUCH

        last = self._processor()
        last.config.attribution_mode = AttributionMode.LAST_TOUCH

        assert first.get_precompute_hash_inputs() != last.get_precompute_hash_inputs()

    def test_precompute_template_contains_time_window_placeholders(self):
        processor = self._processor()
        template, _ = processor.get_attributed_query_for_precomputation()
        assert "{time_window_min}" in template
        assert "{time_window_max}" in template

    def test_precompute_template_parses_with_framework_placeholders(self):
        processor = self._processor()
        template, custom_placeholders = processor.get_attributed_query_for_precomputation()
        placeholders = {
            **custom_placeholders,
            "time_window_min": ast.Constant(value=datetime(2025, 1, 1, tzinfo=UTC)),
            "time_window_max": ast.Constant(value=datetime(2025, 1, 2, tzinfo=UTC)),
        }
        parsed = parse_select(template, placeholders=placeholders)
        assert isinstance(parsed, ast.SelectQuery)

    def test_precompute_template_matches_preagg_table_columns(self):
        processor = self._processor()
        template, _ = processor.get_attributed_query_for_precomputation()
        placeholders: dict[str, ast.Expr] = {
            "time_window_min": ast.Constant(value=datetime(2025, 1, 1, tzinfo=UTC)),
            "time_window_max": ast.Constant(value=datetime(2025, 1, 2, tzinfo=UTC)),
        }
        write_template = parse_select(template, placeholders=placeholders)
        assert isinstance(write_template, ast.SelectQuery)
        aliases = [e.alias for e in write_template.select if isinstance(e, ast.Alias)]
        for col in write_template.select:
            assert isinstance(col, ast.Alias), f"SELECT column not aliased: {col}"
        assert "person_id" in aliases
        from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import TRACKED_FIELDS

        for field in TRACKED_FIELDS:
            assert field.attributed_name in aliases, field.attributed_name
        assert "conversion_value" in aliases
        assert "conversion_timestamp" in aliases
        assert "touchpoint_timestamp" in aliases
        assert "touchpoint_weight" in aliases
        # campaign_id is injected at read time, not stored.
        assert "campaign_id" not in aliases

    def test_precompute_template_raises_for_unsupported_goal_kinds(self):
        processor = ConversionGoalProcessor(
            goal=_make_data_warehouse_goal(),
            index=0,
            team=self.team,
            config=MarketingAnalyticsConfig(),
        )
        with pytest.raises(NotImplementedError):
            processor.get_attributed_query_for_precomputation()

    def test_precompute_skipped_when_tracked_property_restricted(self):
        # Precompute materializes tracked attribution properties into scalar columns, bypassing the
        # per-user masking HogQL applies to events.properties. When such a property is restricted for
        # the user, eligibility must fail so the direct (masked) events query is used instead.
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

    def test_precompute_template_supports_multi_touch(self):
        processor = self._processor()
        processor.config.attribution_mode = AttributionMode.LINEAR
        template, _ = processor.get_attributed_query_for_precomputation()
        placeholders: dict[str, ast.Expr] = {
            "time_window_min": ast.Constant(value=datetime(2025, 1, 1, tzinfo=UTC)),
            "time_window_max": ast.Constant(value=datetime(2025, 1, 2, tzinfo=UTC)),
        }
        parsed = parse_select(template, placeholders=placeholders)
        assert isinstance(parsed, ast.SelectQuery)
        aliases = [e.alias for e in parsed.select if isinstance(e, ast.Alias)]
        assert "touchpoint_weight" in aliases
        assert "touchpoint_timestamp" in aliases
        assert "conversion_timestamp" in aliases

    def test_build_attributed_source_from_precomputed_is_final_aggregateable(self):
        processor = self._processor()
        read = processor.build_attributed_source_from_precomputed(
            job_ids=["00000000-0000-0000-0000-000000000001"],
            date_from=datetime(2025, 1, 1, tzinfo=UTC),
            date_to=datetime(2025, 1, 31, tzinfo=UTC),
        )
        assert isinstance(read, ast.SelectQuery)

        final = processor._build_final_aggregation_query(read)
        assert isinstance(final, ast.SelectQuery)

    def test_tracked_fields_match_preagg_table_schema(self):
        from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
            CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES,
        )

        from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import TRACKED_FIELDS

        assert [f.name for f in TRACKED_FIELDS] == CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES

    def test_hash_inputs_change_when_tracked_fields_change(self):
        from products.marketing_analytics.backend.hogql_queries import conversion_goal_processor as cgp

        processor = self._processor()
        baseline = processor.get_precompute_hash_inputs()

        original = cgp.TRACKED_FIELDS
        try:
            cgp.TRACKED_FIELDS = [*original, cgp.TrackedField("test_field", "utm_test")]
            mutated = self._processor().get_precompute_hash_inputs()
        finally:
            cgp.TRACKED_FIELDS = original

        assert baseline != mutated
        assert baseline["tracked_fields"] != mutated["tracked_fields"]

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_precompute_insert_template_sql_snapshot(self):
        processor = self._processor()
        template, _ = processor.get_attributed_query_for_precomputation()
        placeholders: dict[str, ast.Expr] = {
            "time_window_min": ast.Constant(value=datetime(2025, 1, 1, tzinfo=UTC)),
            "time_window_max": ast.Constant(value=datetime(2025, 1, 2, tzinfo=UTC)),
        }
        parsed = parse_select(template, placeholders=placeholders)
        assert pretty_print_in_tests(to_printed_hogql(parsed, team=self.team), self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_precompute_read_query_sql_snapshot(self):
        processor = self._processor()
        read = processor.build_attributed_source_from_precomputed(
            job_ids=["00000000-0000-0000-0000-000000000001"],
            date_from=datetime(2025, 1, 1, tzinfo=UTC),
            date_to=datetime(2025, 1, 31, tzinfo=UTC),
        )
        final = processor._build_final_aggregation_query(read)
        assert pretty_print_in_tests(to_printed_hogql(final, team=self.team), self.team.pk) == self.snapshot

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
