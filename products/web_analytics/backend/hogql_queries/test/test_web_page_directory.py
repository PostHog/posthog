from typing import Any, Optional

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    PropertyOperator,
    WebPageDirectoryMetric,
    WebPageDirectoryQuery,
    WebPageDirectoryQueryResponse,
    WebPageDirectorySortBy,
)

from posthog.models.utils import uuid7

from products.web_analytics.backend.hogql_queries.web_page_directory import WebPageDirectoryQueryRunner

CRAWLER_USER_AGENT = "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)"
HUMAN_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


class TestWebPageDirectoryQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _pageview(
        self,
        person: str,
        path: str,
        properties: Optional[dict[str, Any]] = None,
        timestamp: str = "2026-01-10T12:00:00Z",
        create_person: bool = True,
    ) -> None:
        if create_person:
            with time_machine.travel("2026-01-10T10:00:00Z", tick=False):
                _create_person(team_id=self.team.pk, distinct_ids=[person], properties={})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=person,
            timestamp=timestamp,
            properties={
                "$host": "example.com",
                "$pathname": path,
                "$current_url": f"https://example.com{path}",
                "$raw_user_agent": HUMAN_USER_AGENT,
                "$session_id": str(uuid7("2026-01-10")),
                **(properties or {}),
            },
        )

    def _crawl(self, path: str, count: int) -> None:
        for _ in range(count):
            _create_event(
                team=self.team,
                event="$http_log",
                distinct_id="crawler",
                timestamp="2026-01-10T12:00:00Z",
                properties={"$host": "example.com", "$pathname": path, "$raw_user_agent": CRAWLER_USER_AGENT},
            )

    def _run(self, **kwargs: Any) -> WebPageDirectoryQueryResponse:
        query = WebPageDirectoryQuery(
            dateRange=DateRange(date_from="2026-01-01", date_to="2026-01-31"),
            **{"properties": [], **kwargs},
        )
        with time_machine.travel("2026-02-01T00:00:00Z", tick=False):
            return WebPageDirectoryQueryRunner(team=self.team, query=query).calculate()

    def test_attributes_search_and_ai_sessions_to_pages(self) -> None:
        self._pageview(
            "google", "/pricing", {"$referrer": "https://www.google.com/", "$referring_domain": "www.google.com"}
        )
        self._pageview("chatgpt", "/pricing", {"utm_source": "chatgpt.com"})
        self._pageview("direct", "/pricing")
        self._pageview("direct", "/docs")

        response = self._run()

        rows = {row.page: row for row in response.results}
        assert [row.page for row in response.results] == ["example.com/pricing", "example.com/docs"]
        pricing = rows["example.com/pricing"]
        assert pricing.visitors is not None and pricing.visitors.current == 3
        assert pricing.googleSearch is not None and pricing.googleSearch.current == 1
        assert pricing.aiReferrals is not None and pricing.aiReferrals.current == 1
        assert rows["example.com/docs"].aiReferrals is not None and rows["example.com/docs"].aiReferrals.current == 0

        by_ai = self._run(sortBy=WebPageDirectorySortBy.AI_REFERRALS)
        assert [row.page for row in by_ai.results] == ["example.com/pricing", "example.com/docs"]

    def test_sorting_by_crawls_includes_pages_no_human_viewed(self) -> None:
        self._pageview("person", "/pricing")
        self._crawl("/llms.txt", 3)
        self._crawl("/pricing", 1)

        response = self._run(sortBy=WebPageDirectorySortBy.AI_CRAWLS)

        assert [(row.page, row.aiCrawls.current if row.aiCrawls else None) for row in response.results] == [
            ("example.com/llms.txt", 3),
            ("example.com/pricing", 1),
        ]
        assert response.results[0].aiCrawlers == 1
        assert response.results[0].aiCrawlerNames == ["GPTBot"]

    @parameterized.expand(
        [
            (
                "keep_trailing_slashes",
                {},
                [("example.com/pricing", 1), ("example.com/pricing/", 1), ("example.com/logo.png", 1)],
            ),
            (
                "exclude_static_assets",
                {"excludeStaticAssets": True},
                [("example.com/pricing", 1), ("example.com/pricing/", 1)],
            ),
            ("search", {"search": "PRICING/"}, [("example.com/pricing/", 1)]),
        ]
    )
    def test_page_key_options(self, _name: str, options: dict[str, Any], expected: list[tuple[str, int]]) -> None:
        self._pageview("a", "/pricing")
        self._pageview("b", "/pricing/")
        self._pageview("c", "/logo.png")

        response = self._run(
            sortBy=WebPageDirectorySortBy.PAGE,
            sortDirection="DESC",
            metrics=[WebPageDirectoryMetric.VISITORS],
            **options,
        )

        assert sorted((row.page, row.visitors.current if row.visitors else 0) for row in response.results) == sorted(
            expected
        )

    def test_paginates_with_has_more(self) -> None:
        for index in range(3):
            self._pageview(f"person-{index}", f"/page-{index}")

        first = self._run(sortBy=WebPageDirectorySortBy.PAGE, sortDirection="ASC", limit=2)
        second = self._run(sortBy=WebPageDirectorySortBy.PAGE, sortDirection="ASC", limit=2, offset=2)

        assert [row.page for row in first.results] == ["example.com/page-0", "example.com/page-1"]
        assert first.hasMore is True
        assert [row.page for row in second.results] == ["example.com/page-2"]
        assert second.hasMore is False

    def test_page_keys_restrict_rows_and_return_site_totals(self) -> None:
        self._pageview("a", "/pricing", {"utm_source": "chatgpt.com"})
        self._pageview("b", "/docs")
        self._crawl("/docs", 2)

        response = self._run(
            pageKeys=["example.com/pricing", "example.com/missing"],
            search="pricing",
            metrics=[
                WebPageDirectoryMetric.VISITORS,
                WebPageDirectoryMetric.AI_REFERRALS,
                WebPageDirectoryMetric.AI_CRAWLS,
                WebPageDirectoryMetric.BOUNCE_RATE,
            ],
            includeSiteTotals=True,
        )

        assert [row.page for row in response.results] == ["example.com/pricing", "example.com/missing"]
        assert response.results[1].visitors is not None and response.results[1].visitors.current == 0
        assert response.results[0].bounceRate == 1.0
        totals = response.siteTotals
        assert totals is not None
        assert totals.serverLogs == 2
        assert totals.visitors is not None and totals.visitors.current == 2
        assert totals.aiReferrals is not None and totals.aiReferrals.current == 1
        assert totals.aiCrawls is not None and totals.aiCrawls.current == 2

    @parameterized.expand(
        [
            ("browser_filter_limits_bounce_sessions", "$browser", "Chrome", 0.0),
            ("pathname_filter_targets_previous_page", "$pathname", "/pricing", 0.5),
        ]
    )
    def test_filters_apply_to_bounce_rate_and_time_on_page(
        self, _name: str, key: str, value: str, expected_bounce_rate: float
    ) -> None:
        session_id = str(uuid7("2026-01-10"))
        self._pageview("a", "/pricing", {"$browser": "Chrome", "$session_id": session_id})
        self._pageview(
            "a",
            "/checkout",
            {
                "$browser": "Chrome",
                "$session_id": session_id,
                "$prev_pageview_pathname": "/pricing",
                "$prev_pageview_duration": 40,
            },
            timestamp="2026-01-10T12:00:40Z",
            create_person=False,
        )
        self._pageview("b", "/pricing", {"$browser": "Firefox"})

        response = self._run(
            pageKeys=["example.com/pricing"],
            metrics=[WebPageDirectoryMetric.BOUNCE_RATE, WebPageDirectoryMetric.TIME_ON_PAGE],
            properties=[EventPropertyFilter(key=key, value=value, operator=PropertyOperator.EXACT)],
        )

        assert response.results[0].bounceRate == expected_bounce_rate
        assert response.results[0].timeOnPageP90 == 40.0
