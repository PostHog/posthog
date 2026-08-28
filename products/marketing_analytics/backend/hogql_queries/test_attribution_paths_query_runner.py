import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    DateRange,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionPathsQuery,
    PropertyMathType,
)

from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models.utils import uuid7
from posthog.test.persons import create_person

from products.marketing_analytics.backend.hogql_queries.attribution_paths_query_runner import (
    PATH_MAX_LENGTH,
    MarketingAnalyticsAttributionPathsQueryRunner,
)

GOAL_ID = "goal-1"
CONVERSION_EVENT = "purchase"
WINDOW_DAYS = 4

CONVERSION_AT = "2023-01-10T12:00:00Z"
ONE_DAY_BEFORE = "2023-01-09T12:00:00Z"
TWO_DAYS_BEFORE = "2023-01-08T12:00:00Z"
THREE_DAYS_BEFORE = "2023-01-07T12:00:00Z"


class TestMarketingAnalyticsAttributionPathsQueryRunner(ClickhouseTestMixin, BaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self._configure_goal()

    def _configure_goal(
        self,
        *,
        counts_as_revenue: bool = True,
        math: PropertyMathType | BaseMathType = PropertyMathType.SUM,
        math_property: str | None = "revenue",
    ) -> None:
        config = self.team.marketing_analytics_config
        config.attribution_window_days = WINDOW_DAYS
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=CONVERSION_EVENT,
                name="Purchases",
                conversion_goal_id=GOAL_ID,
                conversion_goal_name="Purchases",
                schema_map={},
                math=math,
                math_property=math_property,
                counts_as_revenue=counts_as_revenue,
            ).model_dump()
        ]
        config.save()

    def _session(
        self,
        distinct_id: str,
        started_at: str,
        *,
        utm_campaign: str | None = None,
        utm_source: str | None = None,
        utm_medium: str | None = None,
        referring_domain: str = "$direct",
    ) -> None:
        """One session's worth of pageviews — same fixture semantics as the attribution table tests:
        uuid7 seeds the session id so `$start_timestamp` lands on `started_at`, and `$referring_domain`
        defaults to the `$direct` sentinel so untagged sessions classify as Direct."""
        session_id = str(uuid7(started_at))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=started_at,
            properties={
                "$session_id": session_id,
                "$current_url": "https://example.com/",
                "$pathname": "/",
                "$referring_domain": referring_domain,
                **({"utm_campaign": utm_campaign} if utm_campaign else {}),
                **({"utm_source": utm_source} if utm_source else {}),
                **({"utm_medium": utm_medium} if utm_medium else {}),
            },
        )

    def _conversion(self, distinct_id: str, at: str, revenue: float = 100.0) -> None:
        _create_event(
            team=self.team,
            event=CONVERSION_EVENT,
            distinct_id=distinct_id,
            timestamp=at,
            properties={"revenue": revenue},
        )

    def _run(
        self,
        breakdown: MarketingAnalyticsAttributionBreakdown = MarketingAnalyticsAttributionBreakdown.SOURCE,
        *,
        exclude_direct: bool = False,
        exclude_unattributed: bool = False,
        date_from: str = "2023-01-01",
        date_to: str = "2023-01-31",
        lookback_days: int | None = None,
        allow_multiple_conversions: bool | None = None,
        min_touchpoints: int | None = None,
        max_touchpoints: int | None = None,
        limit: int | None = None,
    ):
        flush_persons_and_events()
        query = MarketingAnalyticsAttributionPathsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            excludeDirectTraffic=exclude_direct,
            excludeUnattributed=exclude_unattributed,
            lookbackWindowDays=lookback_days,
            allowMultipleConversionsPerVisitor=allow_multiple_conversions,
            minTouchpoints=min_touchpoints,
            maxTouchpoints=max_touchpoints,
            limit=limit,
            properties=[],
        )
        return MarketingAnalyticsAttributionPathsQueryRunner(query=query, team=self.team).calculate()

    @staticmethod
    def _paths(response) -> dict[tuple[str, ...], int]:
        """{path: conversions} — the shape most assertions need."""
        return {tuple(row.path): row.conversions for row in response.results}

    def test_single_touch_journey_is_a_one_step_path(self):
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)

        response = self._run()

        self.assertEqual(self._paths(response), {("google",): 1})
        self.assertEqual(response.totalConversions, 1)
        self.assertEqual(response.attributedConversions, 1)
        self.assertFalse(response.results[0].pathTruncated)

    def test_touchpoints_appear_in_time_order(self):
        # The person visited via google two days out and newsletter one day out, so the path must read
        # google -> newsletter regardless of what order ClickHouse aggregated the rows in.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google")
        self._session("p1", ONE_DAY_BEFORE, utm_source="newsletter")
        self._conversion("p1", CONVERSION_AT)

        response = self._run()

        self.assertEqual(self._paths(response), {("google", "newsletter"): 1})

    def test_consecutive_repeats_are_preserved_not_collapsed(self):
        # Two google sessions then a conversion is a different journey than one google session, and the
        # two must group separately. Collapsing repeats to "×2" is the frontend's display concern.
        create_person(team=self.team, distinct_ids=["p1", "p2"])
        create_person(team=self.team, distinct_ids=["q1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google")
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)
        self._session("q1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("q1", CONVERSION_AT)

        paths = self._paths(self._run())

        self.assertEqual(paths, {("google", "google"): 1, ("google",): 1})

    def test_identical_paths_group_and_rank_by_conversions(self):
        # Two people with the same journey outrank one person with a different one, and the response
        # comes back ranked most to least.
        for person, source in [("p1", "google"), ("p2", "google"), ("p3", "bing")]:
            create_person(team=self.team, distinct_ids=[person])
            self._session(person, ONE_DAY_BEFORE, utm_source=source)
            self._conversion(person, CONVERSION_AT)

        response = self._run()

        self.assertEqual([tuple(row.path) for row in response.results], [("google",), ("bing",)])
        self.assertEqual(self._paths(response), {("google",): 2, ("bing",): 1})

    def test_touchpoint_count_filter_selects_exact_lengths(self):
        # p1 has a 1-touch journey, p2 a 2-touch one. The filter works on journey length, and the
        # footer's denominator ignores it so shares stay comparable across filter values.
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)
        self._session("p2", TWO_DAYS_BEFORE, utm_source="bing")
        self._session("p2", ONE_DAY_BEFORE, utm_source="newsletter")
        self._conversion("p2", CONVERSION_AT)

        exactly_two = self._run(min_touchpoints=2, max_touchpoints=2)

        self.assertEqual(self._paths(exactly_two), {("bing", "newsletter"): 1})
        self.assertEqual(exactly_two.totalConversions, 2)
        self.assertEqual(exactly_two.attributedConversions, 2)

    def test_open_ended_minimum_keeps_longer_paths(self):
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)
        for started_at, source in [
            (THREE_DAYS_BEFORE, "bing"),
            (TWO_DAYS_BEFORE, "google"),
            (ONE_DAY_BEFORE, "newsletter"),
        ]:
            self._session("p2", started_at, utm_source=source)
        self._conversion("p2", CONVERSION_AT)

        response = self._run(min_touchpoints=2)

        self.assertEqual(self._paths(response), {("bing", "google", "newsletter"): 1})

    def test_invalid_touchpoint_bounds_are_rejected(self):
        with self.assertRaises(ValueError):
            self._run(min_touchpoints=0)
        with self.assertRaises(ValueError):
            self._run(min_touchpoints=3, max_touchpoints=2)

    def test_excluding_direct_drops_direct_steps_from_the_path(self):
        # The journey was google -> Direct -> conversion; with the exclusion the Direct step must
        # disappear from the middle of the path, not just from a standalone row.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_medium="cpc")
        self._session("p1", ONE_DAY_BEFORE)  # Direct
        self._conversion("p1", CONVERSION_AT)

        with_direct = self._paths(self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL))
        self.assertEqual(len(with_direct), 1)
        (path,) = with_direct
        self.assertEqual(path[-1], "Direct")

        without_direct = self._paths(self._run(MarketingAnalyticsAttributionBreakdown.CHANNEL, exclude_direct=True))
        self.assertEqual(len(without_direct), 1)
        (path,) = without_direct
        self.assertEqual(len(path), 1)
        self.assertNotIn("Direct", path)

    def test_excluding_unattributed_drops_none_steps_from_the_path(self):
        # Campaign breakdown: the untagged session renders as a "" step; excluded, the path shrinks to
        # the tagged touch alone.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_campaign="summer")
        self._session("p1", ONE_DAY_BEFORE)  # no utm_campaign
        self._conversion("p1", CONVERSION_AT)

        with_none = self._paths(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))
        self.assertEqual(with_none, {("summer", ""): 1})

        without_none = self._paths(
            self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN, exclude_unattributed=True)
        )
        self.assertEqual(without_none, {("summer",): 1})

    def test_campaign_name_mappings_collapse_dirty_spellings_into_one_step_label(self):
        # Two spellings of one campaign are still two visits, so the path keeps two steps — but both must
        # carry the mapped name, which is what lets the UI collapse them into "Spring Sale 2026 x2"
        # instead of the journey reading as one campaign handing off to another.
        config = self.team.marketing_analytics_config
        config.campaign_name_mappings = {"GoogleAds": {"Spring Sale 2026": ["spring_sale_2026", "spring-sale-2026"]}}
        config.save()

        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google", utm_campaign="spring_sale_2026")
        self._session("p1", ONE_DAY_BEFORE, utm_source="google", utm_campaign="spring-sale-2026")
        self._conversion("p1", CONVERSION_AT)

        paths = self._paths(self._run(MarketingAnalyticsAttributionBreakdown.CAMPAIGN))

        self.assertEqual(paths, {("Spring Sale 2026", "Spring Sale 2026"): 1})

    def test_excluding_unattributed_drops_organic_steps_from_the_path(self):
        # Source breakdown, where the untagged step renders as "organic" rather than "". The paths section
        # has to drop exactly what the table above it drops, or a journey shown here would contradict the
        # weights shown there — which is the whole point of both surfaces sharing one touchpoint definition.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google")
        self._session("p1", ONE_DAY_BEFORE)  # no utm_source -> displayed as "organic"
        self._conversion("p1", CONVERSION_AT)

        with_organic = self._paths(self._run(MarketingAnalyticsAttributionBreakdown.SOURCE))
        self.assertEqual(with_organic, {("google", "organic"): 1})

        without_organic = self._paths(
            self._run(MarketingAnalyticsAttributionBreakdown.SOURCE, exclude_unattributed=True)
        )
        self.assertEqual(without_organic, {("google",): 1})

    def test_long_journeys_group_on_their_most_recent_steps(self):
        # 12 sessions land within the window (hourly, so each is its own touchpoint); the path keeps the
        # most recent PATH_MAX_LENGTH steps and flags the truncation.
        create_person(team=self.team, distinct_ids=["p1"])
        for hour in range(12):
            self._session("p1", f"2023-01-10T{hour:02d}:30:00Z", utm_source=f"source_{hour}")
        self._conversion("p1", "2023-01-10T23:00:00Z")

        response = self._run()

        self.assertEqual(len(response.results), 1)
        row = response.results[0]
        self.assertEqual(len(row.path), PATH_MAX_LENGTH)
        self.assertEqual(row.path, [f"source_{hour}" for hour in range(2, 12)])
        self.assertTrue(row.pathTruncated)

    def test_touches_outside_the_window_are_not_part_of_the_path(self):
        # WINDOW_DAYS is 4: a touch five days before the conversion belongs to no journey, and a
        # conversion whose only touch is out-of-window counts as total but not attributed.
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        self._session("p1", "2023-01-05T12:00:00Z", utm_source="forgotten")  # 5 days out
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)
        self._session("p2", "2023-01-05T12:00:00Z", utm_source="forgotten")
        self._conversion("p2", CONVERSION_AT)

        response = self._run()

        self.assertEqual(self._paths(response), {("google",): 1})
        self.assertEqual(response.totalConversions, 2)
        self.assertEqual(response.attributedConversions, 1)

    def test_one_conversion_per_visitor_keeps_the_first_journey(self):
        # With repeats disallowed, only the journey up to the person's first conversion counts: one
        # path, ending at the google touch, even though a newsletter touch preceded the second purchase.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", TWO_DAYS_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)
        self._session("p1", "2023-01-11T12:00:00Z", utm_source="newsletter")
        self._conversion("p1", "2023-01-12T12:00:00Z")

        response = self._run(allow_multiple_conversions=False)

        self.assertEqual(self._paths(response), {("google",): 1})
        self.assertEqual(response.totalConversions, 1)

    def test_revenue_goal_sums_conversion_value_per_path(self):
        create_person(team=self.team, distinct_ids=["p1"])
        create_person(team=self.team, distinct_ids=["p2"])
        for person, revenue in [("p1", 100.0), ("p2", 50.0)]:
            self._session(person, ONE_DAY_BEFORE, utm_source="google")
            self._conversion(person, CONVERSION_AT, revenue=revenue)

        response = self._run()

        self.assertTrue(response.hasValue)
        self.assertEqual(response.results[0].conversionValue, 150.0)

    def test_non_revenue_goal_reports_no_value(self):
        self._configure_goal(counts_as_revenue=False, math=BaseMathType.TOTAL, math_property=None)
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)

        response = self._run()

        self.assertFalse(response.hasValue)
        self.assertIsNone(response.results[0].conversionValue)

    def test_limit_marks_has_more(self):
        for i in range(3):
            person = f"p{i}"
            create_person(team=self.team, distinct_ids=[person])
            self._session(person, ONE_DAY_BEFORE, utm_source=f"source_{i}")
            self._conversion(person, CONVERSION_AT)

        response = self._run(limit=2)

        self.assertEqual(len(response.results), 2)
        self.assertTrue(response.hasMore)
        self.assertEqual(response.totalConversions, 3)

    def test_per_conversion_path_is_materialized_for_its_two_readers(self):
        # path_rows and the footer both read per_conversion_path; without materialization ClickHouse
        # would run the events scan underneath it twice.
        create_person(team=self.team, distinct_ids=["p1"])
        self._session("p1", ONE_DAY_BEFORE, utm_source="google")
        self._conversion("p1", CONVERSION_AT)
        flush_persons_and_events()

        query = MarketingAnalyticsAttributionPathsQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionPathsQueryRunner(query=query, team=self.team)

        ctes = runner.to_query().ctes
        assert ctes is not None
        self.assertTrue(ctes["per_conversion_path"].materialized)

    # Same three shapes as the attribution table: direct read, alias normalization, classifier.
    @parameterized.expand(
        [
            ("campaign", MarketingAnalyticsAttributionBreakdown.CAMPAIGN),
            ("source", MarketingAnalyticsAttributionBreakdown.SOURCE),
            ("channel", MarketingAnalyticsAttributionBreakdown.CHANNEL),
        ]
    )
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_attribution_paths_sql(self, _name: str, breakdown: MarketingAnalyticsAttributionBreakdown):
        query = MarketingAnalyticsAttributionPathsQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            breakdownBy=breakdown,
            conversionGoalId=GOAL_ID,
            properties=[],
        )
        runner = MarketingAnalyticsAttributionPathsQueryRunner(query=query, team=self.team)
        context = runner._shared_hogql_context
        context.enable_select_queries = True
        printed = prepare_and_print_ast(runner.to_query(), context=context, dialect="clickhouse")
        sql = printed[0] if isinstance(printed, tuple) else printed
        assert pretty_print_in_tests(sql, self.team.pk) == self.snapshot
