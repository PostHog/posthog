from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    CustomBotDefinition,
    CustomBotField,
    CustomBotMatcher,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    WebBotsBreakdown,
    WebBotsTableQuery,
)

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.test.test_web_bots import _collapse_bot_tables
from products.web_analytics.backend.hogql_queries.web_bots import WebBotsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_bots_lazy_precompute import (
    can_use_lazy_precompute,
    classification_key,
)

MODULE = "products.web_analytics.backend.hogql_queries.web_bots_lazy_precompute"
COMMON = "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common"


@override_settings(IN_UNIT_TESTING=True)
class TestWebBotsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=3)

    def query(self, breakdown: WebBotsBreakdown = WebBotsBreakdown.CRAWLER) -> WebBotsTableQuery:
        return WebBotsTableQuery(
            breakdownBy=breakdown,
            properties=[],
            dateRange=DateRange(
                explicitDate=True,
                date_from=(self.start + timedelta(minutes=17)).isoformat(),
                date_to=(self.start + timedelta(hours=3, minutes=17)).isoformat(),
            ),
        )

    def seed(self) -> None:
        for index, minute in enumerate([16, 17, 59, 60, 119, 120, 180, 197, 198]):
            _create_event(
                team=self.team,
                event=("$pageview", "$screen", "$http_log")[index % 3],
                distinct_id="crawler-one",
                timestamp=(self.start + timedelta(minutes=minute)).isoformat(),
                properties={
                    "$raw_user_agent": "Googlebot",
                    "$ip": "203.0.113.7",
                    "$pathname": "/guide" if index % 2 else "/reference",
                    "$host": "example.com",
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

    @parameterized.expand(
        [
            (WebBotsBreakdown.CRAWLER, "UTC"),
            (WebBotsBreakdown.PATH, "UTC"),
            (WebBotsBreakdown.CRAWLER, "America/Los_Angeles"),
            (WebBotsBreakdown.PATH, "America/Los_Angeles"),
        ]
    )
    def test_matches_live_query_including_partial_hours(self, breakdown: WebBotsBreakdown, timezone: str) -> None:
        self.team.timezone = timezone
        self.team.save()
        self.seed()
        query = self.query(breakdown)
        query.useWebAnalyticsPrecompute = False
        live = WebBotsTableQueryRunner(team=self.team, query=query).calculate()
        query.useWebAnalyticsPrecompute = True
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=True),
        ):
            computed = WebBotsTableQueryRunner(team=self.team, query=query).calculate()

        assert "web_bots_preaggregated" in (computed.hogql or ""), [
            _collapse_bot_tables(error or "")
            for error in PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("error", flat=True)
        ]
        assert sorted(computed.results, key=str) == sorted(live.results, key=str)
        assert computed.columns == live.columns
        assert computed.hasMore == live.hasMore

    def test_filters_and_pagination_match_live_query(self) -> None:
        self.seed()
        query = self.query(WebBotsBreakdown.PATH)
        query.properties = [EventPropertyFilter(key="$host", value=["example.com"], operator=PropertyOperator.EXACT)]
        query.limit = 1
        query.useWebAnalyticsPrecompute = False
        live = WebBotsTableQueryRunner(team=self.team, query=query).calculate()
        query.useWebAnalyticsPrecompute = True
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=True),
        ):
            computed = WebBotsTableQueryRunner(team=self.team, query=query).calculate()
        assert "web_bots_preaggregated" in (computed.hogql or "")
        assert computed.results == live.results
        assert computed.hasMore is True

    def test_reuses_jobs_across_bot_tables(self) -> None:
        self.seed()
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=True),
        ):
            crawlers = WebBotsTableQueryRunner(team=self.team, query=self.query()).calculate()
            job_ids = set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True))
            paths = WebBotsTableQueryRunner(team=self.team, query=self.query(WebBotsBreakdown.PATH)).calculate()
        assert "web_bots_preaggregated" in (crawlers.hogql or "")
        assert "web_bots_preaggregated" in (paths.hogql or "")
        assert job_ids
        assert set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True)) == job_ids

    def test_cold_read_does_not_build_inline(self) -> None:
        self.seed()
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{COMMON}.is_background_warming_request", return_value=False),
            patch(f"{COMMON}.enqueue_stale_revalidation") as enqueue,
        ):
            response = WebBotsTableQueryRunner(team=self.team, query=self.query()).calculate()
        assert "web_bots_preaggregated" not in (response.hogql or "")
        assert response.results
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()
        enqueue.assert_called_once()

    def test_precompute_error_falls_back_to_live_query(self) -> None:
        self.seed()
        with (
            patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True),
            patch(f"{MODULE}.web_ensure_precomputed", side_effect=RuntimeError("Precompute unavailable")),
        ):
            response = WebBotsTableQueryRunner(team=self.team, query=self.query()).calculate()
        assert "web_bots_preaggregated" not in (response.hogql or "")
        assert response.results

    def test_comparison_uses_live_query(self) -> None:
        query = self.query()
        query.compareFilter = CompareFilter(compare=True)
        with patch(f"{COMMON}.is_precompute_enabled_for_team", return_value=True):
            assert not can_use_lazy_precompute(WebBotsTableQueryRunner(team=self.team, query=query))

    def test_custom_bot_definitions_change_job_identity(self) -> None:
        original = WebBotsTableQueryRunner(team=self.team, query=self.query())
        query = self.query()
        query.modifiers = HogQLQueryModifiers(
            customBotDefinitions=[
                CustomBotDefinition(
                    id="test-rule",
                    name="Example crawler",
                    key=CustomBotField.FIELD_RAW_USER_AGENT,
                    matcher=CustomBotMatcher.CONTAINS,
                    pattern="ExampleCrawler",
                    category="ai_search",
                )
            ]
        )
        changed = WebBotsTableQueryRunner(team=self.team, query=query)
        assert classification_key(original) != classification_key(changed)
