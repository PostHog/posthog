"""End-to-end equivalence test for the conversion-goal precompute path.

The test seeds events into ClickHouse, runs the funnel CTE query twice —
once going through the events table directly, once going through the
lazy-computed preagg table — and asserts the resulting rows are identical.

This catches parallel-array drift (column order mismatch between write and
read sides) and HAVING mismatches that would silently produce wrong numbers.
"""

from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from posthog.schema import BaseMathType, ConversionGoalFilter1, NodeKind

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL,
)

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import ConversionGoalProcessor
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig


@override_settings(IN_UNIT_TESTING=True)
class TestConversionGoalPrecomputeEquivalence(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self._clean_preaggregation_data()

    def tearDown(self):
        self._clean_preaggregation_data()
        super().tearDown()

    def _clean_preaggregation_data(self):
        sync_execute(TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL())
        PreaggregationJob.objects.all().delete()

    def _seed_events(self):
        """One converter with prior pageviews + one non-converter with pageviews."""
        _create_person(distinct_ids=["user_a"], team=self.team)
        _create_person(distinct_ids=["user_b"], team=self.team)

        # User A: two UTM pageviews, then a purchase.
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_a",
            timestamp=datetime(2025, 1, 5, 10, 0, tzinfo=UTC),
            properties={"utm_campaign": "spring", "utm_source": "google", "utm_medium": "cpc"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_a",
            timestamp=datetime(2025, 1, 7, 10, 0, tzinfo=UTC),
            properties={"utm_campaign": "spring", "utm_source": "google", "utm_medium": "cpc"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_a",
            timestamp=datetime(2025, 1, 10, 10, 0, tzinfo=UTC),
            properties={"value": 100},
        )

        # User B: pageview only, no conversion (should not appear in final output).
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_b",
            timestamp=datetime(2025, 1, 6, 10, 0, tzinfo=UTC),
            properties={"utm_campaign": "spring", "utm_source": "bing", "utm_medium": "cpc"},
        )

        flush_persons_and_events()

    def _make_processor(self, *, precompute: bool) -> ConversionGoalProcessor:
        goal = ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="goal_e2e",
            conversion_goal_name="E2E Goal",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            properties=[],
        )
        config = MarketingAnalyticsConfig()
        config.attribution_window_days = 30
        config.conversion_goal_precomputation_enabled = precompute
        return ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=config)

    def _execute(self, query: ast.SelectQuery) -> list[tuple]:
        return execute_hogql_query(query, team=self.team).results or []

    def test_direct_and_precomputed_paths_return_equivalent_rows(self):
        self._seed_events()

        date_from = datetime(2025, 1, 1, tzinfo=UTC)
        date_to = datetime(2025, 1, 31, tzinfo=UTC)

        # Direct path: no precompute, no date_from/to kwargs — mirrors existing callers.
        direct_processor = self._make_processor(precompute=False)
        direct_query = direct_processor.generate_cte_query(additional_conditions=[])
        direct_rows = sorted(self._execute(direct_query))

        # Precomputed path: same goal, flag on, date range provided.
        preagg_processor = self._make_processor(precompute=True)
        preagg_query = preagg_processor.generate_cte_query(
            additional_conditions=[],
            date_from=date_from,
            date_to=date_to,
        )
        preagg_rows = sorted(self._execute(preagg_query))

        # Same shape and contents. Row set equality is the contract —
        # parallel-array drift would show up as different numeric values here.
        assert direct_rows == preagg_rows, (
            f"Precomputed path diverged from direct path.\ndirect:   {direct_rows}\npreagg:   {preagg_rows}"
        )
