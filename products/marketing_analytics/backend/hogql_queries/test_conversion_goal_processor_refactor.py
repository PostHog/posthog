from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest

from posthog.schema import AttributionMode, BaseMathType, ConversionGoalFilter1, NodeKind

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.test.utils import pretty_print_in_tests

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
    """Tests for the public refactor surface introduced for lazy precomputation.

    These pin the contract that lazy computation will rely on:
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
        # GROUP BY person_id is the marker of the per-person aggregation
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
        """The internal _generate_funnel_query must produce the same shape as
        build_attribution_pipeline(build_array_collection_query(...)).

        This is the key behaviour-preservation guarantee: lazy computation can
        swap the array source without touching attribution.
        """
        processor = self._processor()
        funnel_direct = processor._generate_funnel_query(additional_conditions=[])

        collection = processor.build_array_collection_query(additional_conditions=[])
        composed = processor.build_attribution_pipeline(collection)

        assert type(composed) is type(funnel_direct)
        assert len(composed.select) == len(funnel_direct.select)

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
        """The hash inputs must be JSON-serializable so they can be hashed for cache keys."""
        import json

        processor = self._processor()
        # Must not raise
        json.dumps(processor.get_precompute_hash_inputs(), default=str, sort_keys=True)

    def test_attribution_pipeline_respects_multi_touch_config(self):
        """Switching attribution mode must change the pipeline output."""
        single_touch_processor = self._processor()
        single_touch_processor.config.attribution_mode = AttributionMode.LAST_TOUCH

        multi_touch_processor = self._processor()
        multi_touch_processor.config.attribution_mode = AttributionMode.LINEAR

        collection = single_touch_processor.build_array_collection_query(additional_conditions=[])
        single = single_touch_processor.build_attribution_pipeline(collection)
        multi = multi_touch_processor.build_attribution_pipeline(collection)

        # Different attribution modes produce different SELECT shapes
        assert single.select != multi.select

    def test_hash_inputs_depend_on_attribution_mode(self):
        """Option B materialises the attributed touchpoint at write time, so
        switching modes produces different stored rows and must invalidate
        cache."""
        first = self._processor()
        first.config.attribution_mode = AttributionMode.FIRST_TOUCH

        last = self._processor()
        last.config.attribution_mode = AttributionMode.LAST_TOUCH

        assert first.get_precompute_hash_inputs() != last.get_precompute_hash_inputs()

    def test_precompute_template_contains_time_window_placeholders(self):
        """The template returned for ensure_precomputed must use the framework's
        {time_window_min}/{time_window_max} placeholder syntax verbatim."""
        processor = self._processor()
        template, _ = processor.get_attributed_query_for_precomputation()
        assert "{time_window_min}" in template
        assert "{time_window_max}" in template

    def test_precompute_template_parses_with_framework_placeholders(self):
        """The template must be parseable by parse_select once the framework
        substitutes the time-window placeholders, the same way ensure_precomputed
        does internally."""
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
        """The INSERT template must emit exactly the non-metadata columns of
        the preagg table. team_id, job_id and expires_at are injected by the
        framework; everything else must come from our SELECT."""
        processor = self._processor()
        template, _ = processor.get_attributed_query_for_precomputation()
        placeholders = {
            "time_window_min": ast.Constant(value=datetime(2025, 1, 1, tzinfo=UTC)),
            "time_window_max": ast.Constant(value=datetime(2025, 1, 2, tzinfo=UTC)),
        }
        write_template = parse_select(template, placeholders=placeholders)
        aliases = [e.alias for e in write_template.select if isinstance(e, ast.Alias)]
        # The lazy-computation framework requires every SELECT expression to
        # be aliased so it can build the INSERT column list.
        for col in write_template.select:
            assert isinstance(col, ast.Alias), f"SELECT column not aliased: {col}"
        assert "person_id" in aliases
        # Every tracked field's *_name must be present.
        from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import TRACKED_FIELDS

        for field in TRACKED_FIELDS:
            assert field.attributed_name in aliases, field.attributed_name
        assert "conversion_value" in aliases
        assert "conversion_timestamp" in aliases
        # campaign_id is NOT stored (it's a constant "-" injected at read time).
        assert "campaign_id" not in aliases

    def test_precompute_template_raises_for_unsupported_goal_kinds(self):
        """DataWarehouseNode goals do not use the array-collection pipeline.
        The processor must signal this so the runner falls back to the direct
        path instead of silently producing wrong data."""
        processor = self._processor()
        processor.goal.kind = "DataWarehouseNode"
        try:
            processor.get_attributed_query_for_precomputation()
        except NotImplementedError:
            pass
        else:
            raise AssertionError("Expected NotImplementedError for DataWarehouseNode")

    def test_precompute_template_raises_for_multi_touch(self):
        """Multi-touch modes aren't materialised yet; they must fall back to
        direct. The template method raises so the runner short-circuits."""
        processor = self._processor()
        processor.config.attribution_mode = AttributionMode.LINEAR
        try:
            processor.get_attributed_query_for_precomputation()
        except NotImplementedError:
            pass
        else:
            raise AssertionError("Expected NotImplementedError for multi-touch")

    def test_build_attributed_source_from_precomputed_is_final_aggregateable(self):
        """The read path must produce a SelectQuery that
        ``_build_final_aggregation_query`` accepts — that is the only
        downstream step when using precomputed attribution."""
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
        """The ClickHouse preagg table has one column per TrackedField. A test
        fails loudly when the two drift — the alternative is silent column
        order corruption."""
        from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
            CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES,
        )

        from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import TRACKED_FIELDS

        assert [f.name for f in TRACKED_FIELDS] == CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES

    def test_hash_inputs_change_when_tracked_fields_change(self):
        """Adding/removing a TrackedField changes the column layout of the
        precomputed table. The hash must capture this so prior caches are not
        silently misread after a deploy."""
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
        """Pin the SQL that the lazy-computation framework runs as an INSERT
        to populate the preagg table. Changes here mean the stored data shape
        changed — review carefully."""
        processor = self._processor()
        template, _ = processor.get_attributed_query_for_precomputation()
        placeholders = {
            "time_window_min": ast.Constant(value=datetime(2025, 1, 1, tzinfo=UTC)),
            "time_window_max": ast.Constant(value=datetime(2025, 1, 2, tzinfo=UTC)),
        }
        parsed = parse_select(template, placeholders=placeholders)
        assert pretty_print_in_tests(to_printed_hogql(parsed, team=self.team), self.team.pk) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_precompute_read_query_sql_snapshot(self):
        """Pin the SQL that reads from the preagg table and feeds into
        _build_final_aggregation_query."""
        processor = self._processor()
        read = processor.build_attributed_source_from_precomputed(
            job_ids=["00000000-0000-0000-0000-000000000001"],
            date_from=datetime(2025, 1, 1, tzinfo=UTC),
            date_to=datetime(2025, 1, 31, tzinfo=UTC),
        )
        final = processor._build_final_aggregation_query(read)
        assert pretty_print_in_tests(to_printed_hogql(final, team=self.team), self.team.pk) == self.snapshot
