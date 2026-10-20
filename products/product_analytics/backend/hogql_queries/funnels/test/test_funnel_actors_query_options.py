from datetime import datetime
from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    CompareFilter,
    DateRange,
    EventsNode,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelsQuery,
    HogQLQueryModifiers,
    InsightActorsQueryOptions,
)

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.insight_actors_query_options_runner import InsightActorsQueryOptionsRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.breakdowns import (
    ALL_USERS_COHORT_ID,
    BREAKDOWN_BASELINE_DISPLAY,
    BREAKDOWN_BASELINE_STRING_LABEL,
    BREAKDOWN_NULL_DISPLAY,
)
from posthog.models.instance_setting import override_instance_config
from posthog.test.test_journeys import journeys_for

from products.cohorts.backend.models.cohort import Cohort
from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner


# Compare runs its two period sub-queries in threads outside unit tests; force the serial path so
# they can see this TestCase's uncommitted transaction data (same as the funnel compare test classes).
@override_settings(IN_UNIT_TESTING=True)
class TestFunnelActorsQueryOptions(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _funnels_query(
        self,
        breakdown_filter: Optional[BreakdownFilter] = None,
        compare_filter: Optional[CompareFilter] = None,
        viz_type: str = "steps",
    ) -> FunnelsQuery:
        return FunnelsQuery(
            dateRange=DateRange(date_from="2021-06-07", date_to="2021-06-13"),
            interval="day",
            series=[EventsNode(event="step one"), EventsNode(event="step two")],
            funnelsFilter=FunnelsFilter(
                funnelVizType=viz_type,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit="day",
            ),
            breakdownFilter=breakdown_filter,
            compareFilter=compare_filter,
        )

    def _browser_journeys(self) -> None:
        journeys_for(
            {
                "chrome_user_1": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 10), "properties": {"$browser": "Chrome"}},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 11), "properties": {"$browser": "Chrome"}},
                ],
                "chrome_user_2": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 10), "properties": {"$browser": "Chrome"}},
                ],
                "firefox_user": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 6, 8, 10),
                        "properties": {"$browser": "Firefox"},
                    },
                ],
            },
            self.team,
        )

    def test_no_breakdown_no_compare_returns_empty_options_via_dispatch(self):
        query = InsightActorsQueryOptions(
            source=FunnelsActorsQuery(source=self._funnels_query(), funnelStep=1),
        )
        response = InsightActorsQueryOptionsRunner(query=query, team=self.team).calculate()

        self.assertIsNone(response.breakdown)
        self.assertIsNone(response.compare)

    def test_steps_breakdown_options_start_with_baseline_and_unwrap_single_values(self):
        self._browser_journeys()
        journeys_for(
            {
                "no_browser_user": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 10)},
                ],
            },
            self.team,
        )

        runner = FunnelsQueryRunner(
            query=self._funnels_query(breakdown_filter=BreakdownFilter(breakdown="$browser", breakdown_type="event")),
            team=self.team,
        )
        response = runner.to_actors_query_options()

        self.assertIsNone(response.compare)
        assert response.breakdown is not None
        items = [(item.label, item.value) for item in response.breakdown]
        # Baseline first, then the highest-count value; ties after that have no guaranteed order.
        self.assertEqual(items[0], (BREAKDOWN_BASELINE_DISPLAY, BREAKDOWN_BASELINE_STRING_LABEL))
        self.assertEqual(items[1], ("Chrome", "Chrome"))
        self.assertEqual(
            sorted(items[2:]),
            sorted([("Firefox", "Firefox"), (BREAKDOWN_NULL_DISPLAY, "")]),
        )

    @parameterized.expand([(False,), (True,)])
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False, CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_breakdown_options_execute_their_funnel_on_the_selected_cluster(self, native: bool) -> None:
        source = self._funnels_query(breakdown_filter=BreakdownFilter(breakdown="$browser", breakdown_type="event"))
        source.modifiers = HogQLQueryModifiers(useNewEventsCluster=native, useNewEventsSchema=native)
        query = InsightActorsQueryOptions(source=FunnelsActorsQuery(source=source, funnelStep=1))
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"),
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]),
            patch("posthog.hogql.query.sync_execute", return_value=([], [])) as execute,
        ):
            response = InsightActorsQueryOptionsRunner(query=query, team=self.team, user=self.user).run(
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
            )

        assert response is not None
        assert execute.called
        for call in execute.call_args_list:
            assert call.kwargs["workload"] == (Workload.NEW_EVENTS_CLUSTER if native else Workload.DEFAULT)
            assert ("events_json" in call.args[0]) is native

    def test_steps_multi_property_breakdown_options_are_json_encoded(self):
        journeys_for(
            {
                "user": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 6, 8, 10),
                        "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                    },
                ],
            },
            self.team,
        )

        runner = FunnelsQueryRunner(
            query=self._funnels_query(
                breakdown_filter=BreakdownFilter(breakdown=["$browser", "$os"], breakdown_type="event")
            ),
            team=self.team,
        )
        response = runner.to_actors_query_options()

        assert response.breakdown is not None
        self.assertEqual(
            [(item.label, item.value) for item in response.breakdown],
            [
                (BREAKDOWN_BASELINE_DISPLAY, BREAKDOWN_BASELINE_STRING_LABEL),
                ("Chrome, Mac OS X", '["Chrome","Mac OS X"]'),
            ],
        )

    def test_cohort_breakdown_options_use_raw_cohort_ids(self):
        cohort = Cohort.objects.create(team=self.team, name="my cohort")

        runner = FunnelsQueryRunner(
            query=self._funnels_query(
                breakdown_filter=BreakdownFilter(breakdown=[cohort.pk, "all"], breakdown_type="cohort")
            ),
            team=self.team,
        )
        response = runner.to_actors_query_options()

        assert response.breakdown is not None
        self.assertEqual(
            [(item.label, item.value) for item in response.breakdown],
            [
                (BREAKDOWN_BASELINE_DISPLAY, BREAKDOWN_BASELINE_STRING_LABEL),
                ("my cohort", cohort.pk),
                ("all users", ALL_USERS_COHORT_ID),
            ],
        )

    def test_compare_options_present_and_breakdown_deduped(self):
        self._browser_journeys()

        runner = FunnelsQueryRunner(
            query=self._funnels_query(
                breakdown_filter=BreakdownFilter(breakdown="$browser", breakdown_type="event"),
                compare_filter=CompareFilter(compare=True),
            ),
            team=self.team,
        )
        response = runner.to_actors_query_options()

        assert response.compare is not None
        self.assertEqual(
            [(item.label, item.value) for item in response.compare], [("Current", "current"), ("Previous", "previous")]
        )

        # Compare-merged results carry each breakdown value once per period; options must not.
        assert response.breakdown is not None
        values = [item.value for item in response.breakdown]
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(values[0], BREAKDOWN_BASELINE_STRING_LABEL)
        self.assertEqual(set(values[1:]), {"Chrome", "Firefox"})

    @parameterized.expand(
        [
            ("whole_float_matches_frontend_number", 1.0, 1),
            ("fractional_float", 1.5, "1.5"),
            ("bool_before_int", True, "True"),
            ("int", 2, 2),
            ("string", "x", "x"),
            ("single_element_list_unwrapped", ["a"], "a"),
            ("multi_element_list_json", ["a", "b"], '["a","b"]'),
        ]
    )
    def test_breakdown_option_value_wire_contract(self, _name, value, expected):
        # Option values must survive the results JSON round-trip: Python str(1.0) is "1.0" while
        # the frontend holds 1, so a stringified whole float breaks dropdown selection matching.
        self.assertEqual(FunnelsQueryRunner._breakdown_option_value(value), expected)

    def test_trends_viz_breakdown_from_rows_and_compare_suppressed(self):
        self._browser_journeys()

        runner = FunnelsQueryRunner(
            query=self._funnels_query(
                breakdown_filter=BreakdownFilter(breakdown="$browser", breakdown_type="event"),
                compare_filter=CompareFilter(compare=True),
                viz_type="trends",
            ),
            team=self.team,
        )
        response = runner.to_actors_query_options()

        self.assertIsNone(response.compare)
        assert response.breakdown is not None
        values = [item.value for item in response.breakdown]
        self.assertEqual(values[0], BREAKDOWN_BASELINE_STRING_LABEL)
        self.assertEqual(set(values[1:]), {"Chrome", "Firefox"})
