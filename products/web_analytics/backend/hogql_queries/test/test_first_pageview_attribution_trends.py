from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    DateRange,
    EventsNode,
    HogQLQueryModifiers,
    PropertyOperator,
    QueryLogTags,
    SessionPropertyFilter,
    SessionTableVersion,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner

from products.web_analytics.backend.hogql_queries.test.first_pageview_attribution_test_base import (
    FirstPageviewAttributionTestMixin,
)


@override_settings(IN_UNIT_TESTING=True)
class TestFirstPageviewAttributionTrends(FirstPageviewAttributionTestMixin, ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2024-07-30"

    def _paid_search_visitors(self, flag_on, tagged, value="Paid Search"):
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-06-01", date_to="2024-06-30"),
            series=[EventsNode(event="$pageview", math=BaseMathType.DAU)],
            properties=[SessionPropertyFilter(key="$channel_type", value=value, operator=PropertyOperator.EXACT)],
            tags=QueryLogTags(productKey="web_analytics") if tagged else None,
            modifiers=HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2),
        )
        with self._patch_first_pageview_flag(flag_on), freeze_time(self.QUERY_TIMESTAMP):
            response = TrendsQueryRunner(team=self.team, query=query).calculate()
        return response.results[0]["count"]

    @parameterized.expand(
        [
            ("web_analytics_flag_on", True, True, 1),
            ("web_analytics_flag_off", False, True, 0),
            ("other_product_flag_on", True, False, 0),
            ("web_analytics_flag_on_list_value", True, True, 1, ["Paid Search", "Email"]),
        ]
    )
    def test_trends_session_filter_rewrite(self, _name, flag_on, tagged, expected, value="Paid Search"):
        # A query from any other product must keep entry attribution: `tags` are
        # stripped from the cache key, so a leak here would also let the two
        # share a cache entry.
        self._seed_ssr_poisoned_session()

        assert self._paid_search_visitors(flag_on=flag_on, tagged=tagged, value=value) == expected

    @parameterized.expand(
        [
            ("line_graph_flag_on", ChartDisplayType.ACTIONS_LINE_GRAPH, True, 1),
            ("line_graph_flag_off", ChartDisplayType.ACTIONS_LINE_GRAPH, False, 0),
            ("heatmap_flag_on", ChartDisplayType.CALENDAR_HEATMAP, True, 1),
            ("heatmap_flag_off", ChartDisplayType.CALENDAR_HEATMAP, False, 0),
        ]
    )
    def test_series_level_session_filter_rewrite(self, _name, display, flag_on, expected):
        # Active Hours puts the filter on the series, not the query, and renders
        # through the calendar heatmap runner: a different runner reading a
        # different property list.
        self._seed_ssr_poisoned_session()

        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-06-01", date_to="2024-06-30"),
            series=[
                EventsNode(
                    event="$pageview",
                    math=BaseMathType.DAU,
                    properties=[
                        SessionPropertyFilter(key="$channel_type", value="Paid Search", operator=PropertyOperator.EXACT)
                    ],
                )
            ],
            trendsFilter=TrendsFilter(display=display),
            tags=QueryLogTags(productKey="web_analytics"),
            modifiers=HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2),
        )
        with self._patch_first_pageview_flag(flag_on), freeze_time(self.QUERY_TIMESTAMP):
            results = get_query_runner(query, team=self.team).calculate().results

        assert results[0]["count"] == expected

    def test_rewritten_filter_changes_trends_cache_key(self):
        query = TrendsQuery(
            dateRange=DateRange(date_from="2024-06-01", date_to="2024-06-30"),
            series=[EventsNode(event="$pageview", math=BaseMathType.DAU)],
            properties=[
                SessionPropertyFilter(key="$channel_type", value="Paid Search", operator=PropertyOperator.EXACT)
            ],
            tags=QueryLogTags(productKey="web_analytics"),
        )

        def cache_key(flag_on):
            with self._patch_first_pageview_flag(flag_on):
                return TrendsQueryRunner(team=self.team, query=query).get_cache_key()

        assert cache_key(flag_on=True) != cache_key(flag_on=False)
