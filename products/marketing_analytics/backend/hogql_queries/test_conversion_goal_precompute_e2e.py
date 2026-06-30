from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import AttributionMode, BaseMathType, ConversionGoalFilter1

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL,
)
from posthog.clickhouse.preaggregation.marketing_conversions_sql import TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL
from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL

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
        sync_execute(TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL())
        sync_execute(TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL())
        PreaggregationJob.objects.all().delete()

    def _seed_events(self):
        """Seed a realistic mix that exercises every multi-touch branch.

        - user_a: 3 distinct touchpoints + 1 conversion → multi-touch distributes weight
          across spring, summer, fall (LINEAR = 1/3 each, POSITION_BASED puts 40% on
          spring and 40% on fall, TIME_DECAY favours fall).
        - user_b: 2 same-UTM touchpoints + 1 conversion → tests aggregation when multi-touch
          assigns fractional weight to the same (campaign, source) key twice.
        - user_c: 3 touchpoints + 2 conversions at different times → each conversion gets its
          own attribution window; mode is applied per-conversion.
        - user_d: 1 touchpoint inside window + 1 touchpoint OUTSIDE (60 days prior, window=30)
          + 1 conversion → the out-of-window pageview must be excluded identically in both
          paths.
        - user_e: conversion with no touchpoint → organic row; weight logic must not blow up.
        - user_f: pageview only, no conversion → must not appear anywhere.
        """
        for distinct_id in ("user_a", "user_b", "user_c", "user_d", "user_e", "user_f"):
            _create_person(distinct_ids=[distinct_id], team=self.team)

        # user_a: 3 distinct campaigns in order → spring, summer, fall.
        for day, (campaign, source, medium) in [
            (3, ("spring", "google", "cpc")),
            (6, ("summer", "facebook", "social")),
            (9, ("fall", "bing", "cpc")),
        ]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_a",
                timestamp=datetime(2025, 1, day, 10, 0, tzinfo=UTC),
                properties={"utm_campaign": campaign, "utm_source": source, "utm_medium": medium},
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_a",
            timestamp=datetime(2025, 1, 12, 10, 0, tzinfo=UTC),
            properties={"value": 100},
        )

        # user_b: same (campaign, source) twice → multi-touch should aggregate into one row.
        for day in (4, 8):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_b",
                timestamp=datetime(2025, 1, day, 10, 0, tzinfo=UTC),
                properties={"utm_campaign": "winter", "utm_source": "twitter", "utm_medium": "social"},
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_b",
            timestamp=datetime(2025, 1, 11, 10, 0, tzinfo=UTC),
            properties={"value": 50},
        )

        # user_c: 3 touchpoints, 2 conversions (each should see a different attribution state).
        for day, (campaign, source) in [
            (2, ("newyear", "google")),
            (6, ("spring", "google")),
            (13, ("fall", "facebook")),
        ]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_c",
                timestamp=datetime(2025, 1, day, 10, 0, tzinfo=UTC),
                properties={"utm_campaign": campaign, "utm_source": source, "utm_medium": "cpc"},
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_c",
            timestamp=datetime(2025, 1, 7, 10, 0, tzinfo=UTC),
            properties={"value": 30},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_c",
            timestamp=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            properties={"value": 40},
        )

        # user_d: one touchpoint INSIDE window, one OUTSIDE (60 days prior with window=30).
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_d",
            timestamp=datetime(2024, 11, 10, 10, 0, tzinfo=UTC),  # ~63 days before conversion
            properties={"utm_campaign": "stale", "utm_source": "google", "utm_medium": "cpc"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_d",
            timestamp=datetime(2025, 1, 5, 10, 0, tzinfo=UTC),
            properties={"utm_campaign": "fresh", "utm_source": "google", "utm_medium": "cpc"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_d",
            timestamp=datetime(2025, 1, 12, 10, 0, tzinfo=UTC),
            properties={"value": 20},
        )

        # user_e: conversion with no touchpoint (organic).
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_e",
            timestamp=datetime(2025, 1, 14, 10, 0, tzinfo=UTC),
            properties={"value": 10},
        )

        # user_f: pageview only, no purchase.
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_f",
            timestamp=datetime(2025, 1, 9, 10, 0, tzinfo=UTC),
            properties={"utm_campaign": "spring", "utm_source": "bing", "utm_medium": "cpc"},
        )

        flush_persons_and_events()

    def _make_processor(
        self, *, precompute: bool, attribution_mode: AttributionMode = AttributionMode.LAST_TOUCH
    ) -> ConversionGoalProcessor:
        goal = ConversionGoalFilter1(
            kind="EventsNode",
            event="purchase",
            conversion_goal_id="goal_e2e",
            conversion_goal_name="E2E Goal",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            properties=[],
        )
        config = MarketingAnalyticsConfig()
        config.attribution_window_days = 30
        config.attribution_mode = attribution_mode
        config.conversion_goal_precomputation_enabled = precompute
        return ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=config)

    def _execute(self, query: ast.SelectQuery) -> list[tuple]:
        return execute_hogql_query(query, team=self.team).results or []

    @parameterized.expand(
        [
            (AttributionMode.LAST_TOUCH,),
            (AttributionMode.FIRST_TOUCH,),
            (AttributionMode.LINEAR,),
            (AttributionMode.TIME_DECAY,),
            (AttributionMode.POSITION_BASED,),
        ]
    )
    def test_direct_and_precomputed_paths_return_equivalent_rows(self, attribution_mode: AttributionMode):
        self._seed_events()

        date_from = datetime(2025, 1, 1, tzinfo=UTC)
        date_to = datetime(2025, 1, 31, tzinfo=UTC)

        direct_processor = self._make_processor(precompute=False, attribution_mode=attribution_mode)
        direct_query = direct_processor.generate_cte_query(additional_conditions=[])
        direct_rows = sorted(self._execute(direct_query))

        preagg_processor = self._make_processor(precompute=True, attribution_mode=attribution_mode)
        preagg_query = preagg_processor.generate_cte_query(
            additional_conditions=[],
            date_from=date_from,
            date_to=date_to,
        )
        preagg_rows = sorted(self._execute(preagg_query))

        assert _round_rows(direct_rows) == _round_rows(preagg_rows), (
            f"{attribution_mode}: precompute diverged from direct path.\ndirect: {direct_rows}\npreagg: {preagg_rows}"
        )

    @parameterized.expand(
        [
            (AttributionMode.LAST_TOUCH,),
            (AttributionMode.FIRST_TOUCH,),
            (AttributionMode.LINEAR,),
            (AttributionMode.TIME_DECAY,),
            (AttributionMode.POSITION_BASED,),
        ]
    )
    def test_precompute_matches_direct_in_non_utc_timezone(self, attribution_mode: AttributionMode):
        self.team.timezone = "US/Pacific"
        self.team.save()
        self._seed_events()

        date_from = datetime(2025, 1, 1, tzinfo=UTC)
        date_to = datetime(2025, 1, 31, tzinfo=UTC)

        direct_processor = self._make_processor(precompute=False, attribution_mode=attribution_mode)
        direct_rows = sorted(self._execute(direct_processor.generate_cte_query(additional_conditions=[])))

        preagg_processor = self._make_processor(precompute=True, attribution_mode=attribution_mode)
        preagg_rows = sorted(
            self._execute(
                preagg_processor.generate_cte_query(additional_conditions=[], date_from=date_from, date_to=date_to)
            )
        )

        assert preagg_rows, f"{attribution_mode}: precompute returned no rows for a non-UTC team"
        assert _round_rows(direct_rows) == _round_rows(preagg_rows)

    def test_reused_wide_job_excludes_out_of_range_conversions(self):
        _create_person(distinct_ids=["user_dec"], team=self.team)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_dec",
            timestamp=datetime(2024, 12, 10, 10, 0, tzinfo=UTC),
            properties={"utm_campaign": "december", "utm_source": "google", "utm_medium": "cpc"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_dec",
            timestamp=datetime(2024, 12, 12, 10, 0, tzinfo=UTC),
            properties={"value": 99},
        )
        self._seed_events()

        processor = self._make_processor(precompute=True)
        # Materialize a job spanning December — a wider prior request the lazy framework reuses for the
        # narrow one below (find_existing_jobs matches the overlapping wider job).
        processor.generate_cte_query(
            additional_conditions=[],
            date_from=datetime(2024, 12, 1, tzinfo=UTC),
            date_to=datetime(2025, 1, 31, tzinfo=UTC),
        )
        narrow_rows = self._execute(
            processor.generate_cte_query(
                additional_conditions=[],
                date_from=datetime(2025, 1, 1, tzinfo=UTC),
                date_to=datetime(2025, 1, 31, tzinfo=UTC),
            )
        )

        assert narrow_rows, "expected in-range conversions in the narrow window"
        assert all("december" not in row for row in narrow_rows), (
            f"out-of-range December conversion leaked from the reused wider job: {narrow_rows}"
        )


def _round_rows(rows: list[tuple]) -> list[tuple]:
    """Round floats to avoid weight-multiplication rounding noise between paths."""
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in row) for row in rows]
