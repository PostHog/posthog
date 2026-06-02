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
        - user_g: 2 touchpoints where utm_medium is OMITTED (only campaign + source set) +
          1 conversion → regression guard for the array-alignment bug: the optional UTM
          field's slot must survive the array-collection arrayFilter so its index stays
          aligned with utm_timestamps. Pre-fix, dropping the empty medium re-indexed the
          per-field array and made indexOf-based attribution look up the medium from an
          unrelated row.
        """
        for distinct_id in ("user_a", "user_b", "user_c", "user_d", "user_e", "user_f", "user_g"):
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

        # user_g: regression case for the array-misalignment bug. Three UTM pageviews where
        # the MIDDLE one has no utm_medium, sandwiched between two with non-empty medium.
        # Pre-fix the per-field arrayFilter(notEmpty) dropped only the middle medium slot,
        # leaving utm_medium_array length 2 while utm_timestamps length is 3. Last-touch
        # attribution for the day-9 purchase resolves to the day-8 "partial" touchpoint;
        # indexOf(utm_timestamps, day8) = 2, and utm_medium_array[2] then reads "social"
        # from the day-12 row instead of the legitimate "" → cross-row medium leak.
        for day, props in [
            (3, {"utm_campaign": "early", "utm_source": "google", "utm_medium": "cpc"}),
            (8, {"utm_campaign": "partial", "utm_source": "bing"}),  # no medium
            (12, {"utm_campaign": "late", "utm_source": "facebook", "utm_medium": "social"}),
        ]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_g",
                timestamp=datetime(2025, 1, day, 10, 0, tzinfo=UTC),
                properties=props,
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_g",
            timestamp=datetime(2025, 1, 9, 10, 0, tzinfo=UTC),
            properties={"value": 25},
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

    def test_per_field_utm_arrays_stay_aligned_with_utm_timestamps(self):
        """Array-level regression for the per-field arrayFilter desync.

        The attribution pipeline relies on parallel per-person arrays — utm_timestamps,
        utm_campaigns, utm_sources, utm_mediums, ... — all the same length so that
        indexOf(utm_timestamps, picked_ts) yields a valid index into every other array.

        Pre-fix, arrayFilter(notEmpty) on each individual UTM array dropped slots
        wherever an optional UTM field happened to be empty on a real touchpoint
        (e.g. utm_medium absent on a campaign+source-tagged pageview). That shrunk
        only the affected array, desyncing it from utm_timestamps and making the
        attribution read a medium from an unrelated sibling touchpoint.

        user_g has 3 UTM pageviews where the middle one omits utm_medium — pre-fix,
        utm_mediums for user_g came back length 2 while utm_timestamps was length 3.
        """
        self._seed_events()

        processor = self._make_processor(precompute=False)
        array_query = processor.build_array_collection_query(additional_conditions=[])

        # Wrap the array-collection subquery to expose per-array lengths per person.
        diagnostic_query = ast.SelectQuery(
            select=[
                ast.Field(chain=["person_id"]),
                ast.Alias(alias="ts_len", expr=ast.Call(name="length", args=[ast.Field(chain=["utm_timestamps"])])),
                *[
                    ast.Alias(
                        alias=f"{field_name}_len",
                        expr=ast.Call(name="length", args=[ast.Field(chain=[field_name])]),
                    )
                    for field_name in ("utm_campaigns", "utm_sources", "utm_mediums")
                ],
            ],
            select_from=ast.JoinExpr(table=array_query, alias="ac"),
        )

        rows = self._execute(diagnostic_query)
        assert rows, "array-collection returned no persons — fixture problem"

        for person_id, ts_len, camp_len, src_len, medium_len in rows:
            assert camp_len == ts_len, f"person {person_id}: utm_campaigns ({camp_len}) != utm_timestamps ({ts_len})"
            assert src_len == ts_len, f"person {person_id}: utm_sources ({src_len}) != utm_timestamps ({ts_len})"
            assert medium_len == ts_len, (
                f"person {person_id}: utm_mediums ({medium_len}) != utm_timestamps ({ts_len}) — "
                f"per-field arrayFilter dropped an empty medium slot, attribution will read from the wrong row"
            )


def _round_rows(rows: list[tuple]) -> list[tuple]:
    """Round floats to avoid weight-multiplication rounding noise between paths."""
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in row) for row in rows]
