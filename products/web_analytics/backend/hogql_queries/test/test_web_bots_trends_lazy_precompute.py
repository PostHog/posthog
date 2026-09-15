from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    GroupNode,
    IntervalType,
    NodeKind,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
    WebBotsBreakdown,
    WebBotsTableQuery,
)

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_bots import BOT_ANALYTICS_EVENTS, WebBotsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_bots_trends_lazy_precompute import (
    bots_trends_breakdown,
    execute_lazy_precomputed_bots_trends,
)
from products.web_analytics.backend.hogql_queries.web_trends import WebTrendsQueryRunner

MODULE = "products.web_analytics.backend.hogql_queries.web_bots_trends_lazy_precompute"
COMMON = "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common"


@override_settings(IN_UNIT_TESTING=True)
class TestWebBotsTrendsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3)

    def query(
        self,
        breakdown: str = "$virt_bot_name",
        interval: IntervalType = IntervalType.HOUR,
        hours: int = 6,
        extra_filters: tuple[EventPropertyFilter, ...] = (),
    ) -> TrendsQuery:
        return TrendsQuery(
            kind=NodeKind.TRENDS_QUERY,
            dateRange=DateRange(
                date_from=self.start.isoformat(),
                date_to=(self.start + timedelta(hours=hours)).isoformat(),
            ),
            interval=interval,
            series=[
                GroupNode(
                    kind=NodeKind.GROUP_NODE,
                    name=", ".join(BOT_ANALYTICS_EVENTS),
                    custom_name="Requests",
                    operator=FilterLogicalOperator.OR_,
                    math=BaseMathType.TOTAL,
                    nodes=[
                        EventsNode(event=event, math=BaseMathType.TOTAL, name=event) for event in BOT_ANALYTICS_EVENTS
                    ],
                )
            ],
            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            breakdownFilter=BreakdownFilter(breakdown=breakdown, breakdown_type="event"),
            properties=[
                *extra_filters,
                EventPropertyFilter(key="$virt_is_bot", value=["true"], operator=PropertyOperator.EXACT),
                EventPropertyFilter(key="$virt_bot_name", value=[""], operator=PropertyOperator.IS_NOT),
            ],
        )

    def seed(self) -> None:
        for index, minute in enumerate([16, 17, 59, 60, 119, 120, 180, 197, 198, 301]):
            _create_event(
                team=self.team,
                event=BOT_ANALYTICS_EVENTS[index % 3],
                distinct_id="crawler-one",
                timestamp=(self.start + timedelta(minutes=minute)).isoformat(),
                properties={
                    "$raw_user_agent": "Googlebot",
                    "$ip": "203.0.113.7",
                    "$pathname": "/guide" if index % 2 else "/reference",
                    "$host": "example.com" if index % 4 else "docs.example.com",
                },
            )
        for agent, pathname in [("GPTBot", "/guide"), ("GPTBot", None), ("GPTBot", ""), ("Mozilla/5.0", "/guide")]:
            _create_event(
                team=self.team,
                event="$http_log",
                distinct_id="crawler-two",
                timestamp=(self.start + timedelta(hours=2, minutes=30)).isoformat(),
                properties={"$raw_user_agent": agent, "$ip": "203.0.113.8", "$pathname": pathname},
            )

    def precomputed(self, query: TrendsQuery):
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=True),
        ):
            return execute_lazy_precomputed_bots_trends(WebTrendsQueryRunner(team=self.team, query=query))

    @parameterized.expand(
        [
            ("$virt_bot_name", IntervalType.HOUR, "UTC"),
            ("$virt_traffic_category", IntervalType.HOUR, "UTC"),
            ("$host", IntervalType.HOUR, "UTC"),
            ("$pathname", IntervalType.HOUR, "UTC"),
            ("$virt_bot_name", IntervalType.DAY, "UTC"),
            ("$pathname", IntervalType.HOUR, "America/Los_Angeles"),
            ("$host", IntervalType.DAY, "America/Los_Angeles"),
        ]
    )
    def test_matches_live_trends(self, breakdown: str, interval: IntervalType, timezone: str) -> None:
        self.team.timezone = timezone
        self.team.save()
        self.seed()
        query = self.query(breakdown, interval)
        live = TrendsQueryRunner(team=self.team, query=query).calculate().results

        served = self.precomputed(query)
        assert served is not None, list(
            PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("error", flat=True)
        )
        results, _ = served
        assert [(item["label"], item["breakdown_value"], item["data"], item["days"]) for item in results] == [
            (item["label"], item["breakdown_value"], item["data"], item["days"]) for item in live
        ]

    def test_matches_live_trends_with_a_user_filter(self) -> None:
        self.seed()
        query = self.query(
            "$virt_bot_name",
            extra_filters=(EventPropertyFilter(key="$host", value=["example.com"], operator=PropertyOperator.EXACT),),
        )
        live = TrendsQueryRunner(team=self.team, query=query).calculate().results

        served = self.precomputed(query)
        assert served is not None
        results, _ = served
        assert [item["data"] for item in results] == [item["data"] for item in live]
        assert [item["breakdown_value"] for item in results] == [item["breakdown_value"] for item in live]

    def test_reuses_the_jobs_the_bot_tables_built(self) -> None:
        self.seed()
        table_query = WebBotsTableQuery(
            breakdownBy=WebBotsBreakdown.CRAWLER,
            properties=[],
            dateRange=DateRange(
                explicitDate=True,
                date_from=self.start.isoformat(),
                date_to=(self.start + timedelta(hours=6)).isoformat(),
            ),
        )
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=True),
        ):
            WebBotsTableQueryRunner(team=self.team, query=table_query).calculate()
        job_ids = set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True))
        assert job_ids

        assert self.precomputed(self.query("$pathname")) is not None
        assert set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True)) == job_ids

    def test_cold_read_does_not_build_inline(self) -> None:
        self.seed()
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=False),
            patch(f"{COMMON}.enqueue_stale_revalidation") as enqueue,
        ):
            served = execute_lazy_precomputed_bots_trends(WebTrendsQueryRunner(team=self.team, query=self.query()))
        assert served is None
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()
        enqueue.assert_called_once()

    def test_precompute_error_falls_back_to_the_live_path(self) -> None:
        self.seed()
        query = self.query()
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{MODULE}.ensure_web_bots_precomputed", side_effect=RuntimeError("Precompute unavailable")),
        ):
            assert execute_lazy_precomputed_bots_trends(WebTrendsQueryRunner(team=self.team, query=query)) is None
        assert TrendsQueryRunner(team=self.team, query=query).calculate().results

    @parameterized.expand(
        [
            ("unstored_breakdown", "$browser", None, None),
            ("compare_range", None, CompareFilter(compare=True), None),
            ("unsupported_interval", None, None, IntervalType.MINUTE),
        ]
    )
    def test_unsupported_shapes_stay_on_the_live_path(
        self,
        _name: str,
        breakdown: str | None,
        compare: CompareFilter | None,
        interval: IntervalType | None,
    ) -> None:
        query = self.query(breakdown or "$virt_bot_name", interval or IntervalType.HOUR)
        query.compareFilter = compare
        assert bots_trends_breakdown(query) is None

    def test_other_bucket_reports_has_more(self) -> None:
        for index in range(30):
            _create_event(
                team=self.team,
                event="$http_log",
                distinct_id=f"crawler-{index}",
                timestamp=(self.start + timedelta(hours=1)).isoformat(),
                properties={"$raw_user_agent": "GPTBot", "$pathname": f"/page-{index}"},
            )
        served = self.precomputed(self.query("$pathname"))
        assert served is not None
        results, has_more = served
        assert has_more is True
        assert any(item["breakdown_value"] == "$$_posthog_breakdown_other_$$" for item in results)
