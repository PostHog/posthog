from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from posthog.schema import (
    ActionConversionGoal,
    CustomEventConversionGoal,
    DateRange,
    EventPropertyFilter,
    PropertyOperator,
    WebAgentAnalyticsQuery,
    WebAgentAnalyticsQueryResponse,
    WebAgentAnalyticsQueryType,
    WebAgentContentGrouping,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from products.web_analytics.backend.hogql_queries.web_agent_analytics import WebAgentAnalyticsQueryRunner

ASSISTANT_USER_AGENT = "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)"
CRAWLER_USER_AGENT = "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)"
HUMAN_USER_AGENT = "Mozilla/5.0 AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"


class TestWebAgentAnalyticsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_http_event(
        self,
        distinct_id: str,
        pathname: str,
        status_code: int,
        *,
        user_agent: str = ASSISTANT_USER_AGENT,
        timestamp: str = "2026-08-10T12:00:00Z",
        host: str = "example.com",
        referrer: str | None = None,
    ) -> None:
        properties: dict[str, object | None] = {
            "$host": host,
            "$pathname": pathname,
            "$raw_user_agent": user_agent,
            "proxy_status_code": status_code,
        }
        if referrer is not None:
            properties["proxy_referer"] = referrer
        _create_event(
            team=self.team,
            event="$http_log",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
        )

    def _run(
        self,
        query_type: WebAgentAnalyticsQueryType,
        *,
        include_crawlers: bool = False,
        conversion_goal: ActionConversionGoal | CustomEventConversionGoal | None = None,
        content_grouping: WebAgentContentGrouping = WebAgentContentGrouping.NORMALIZED,
        properties: list[EventPropertyFilter] | None = None,
        llms_txt_url: str | None = None,
        journey_key: str | None = None,
        intent_key: str | None = None,
        limit: int = 100,
        date_from: str = "2026-08-01",
    ) -> WebAgentAnalyticsQueryResponse:
        query = WebAgentAnalyticsQuery(
            queryType=query_type,
            dateRange=DateRange(date_from=date_from, date_to="2026-08-20"),
            includeCrawlers=include_crawlers,
            contentGrouping=content_grouping,
            conversionGoal=conversion_goal,
            properties=properties or [],
            llmsTxtUrl=llms_txt_url,
            journeyKey=journey_key,
            intentKey=intent_key,
            limit=limit,
        )
        with freeze_time("2026-08-20T18:00:00Z"):
            return WebAgentAnalyticsQueryRunner(team=self.team, query=query).calculate()

    @staticmethod
    def _first_row(response: WebAgentAnalyticsQueryResponse) -> dict[str, object]:
        assert response.columns is not None
        assert response.results
        return dict(zip(response.columns, response.results[0], strict=True))

    @staticmethod
    def _rows(response: WebAgentAnalyticsQueryResponse) -> list[dict[str, object]]:
        assert response.columns is not None
        return [dict(zip(response.columns, row, strict=True)) for row in response.results]

    def test_overview_excludes_humans_assets_and_unpaired_markdown_fetches(self) -> None:
        for distinct_id in ("paired", "markdown-only", "human", "crawler"):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={})

        self._create_http_event("paired", "/docs/start", 200)
        self._create_http_event("paired", "/docs/start.md", 200)
        self._create_http_event("markdown-only", "/docs/other.md", 200)
        self._create_http_event("paired", "/logo.svg", 200)
        self._create_http_event("human", "/docs/start", 200, user_agent=HUMAN_USER_AGENT)
        self._create_http_event("crawler", "/docs/start", 200, user_agent=CRAWLER_USER_AGENT)
        self._create_http_event("paired", "/docs/old", 404, timestamp="2026-07-20T12:00:00Z")
        flush_persons_and_events()

        default_row = self._first_row(self._run(WebAgentAnalyticsQueryType.OVERVIEW))
        crawler_row = self._first_row(self._run(WebAgentAnalyticsQueryType.OVERVIEW, include_crawlers=True))

        self.assertEqual(default_row["active_clients"], 2)
        self.assertEqual(default_row["server_requests"], 3)
        self.assertEqual(default_row["client_navigations"], 0)
        self.assertEqual(default_row["excluded_requests"], 1)
        self.assertEqual(default_row["wasted"], 1)
        self.assertEqual(default_row["waste_pages"], 1)
        self.assertEqual(crawler_row["active_clients"], 3)
        self.assertEqual(crawler_row["server_requests"], 4)

    def test_overview_counts_agents_that_reach_the_conversion_goal_inside_the_window(self) -> None:
        for distinct_id in ("converted-agent", "agent-only", "human-only", "wrong-order", "expired"):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={})

        self._create_http_event("converted-agent", "/docs/start", 200)
        self._create_http_event("agent-only", "/docs/start", 200)
        self._create_http_event("wrong-order", "/docs/start", 200, timestamp="2026-08-10T12:10:00Z")
        self._create_http_event("expired", "/docs/start", 200, timestamp="2026-08-10T00:00:00Z")
        for distinct_id, timestamp in (
            ("converted-agent", "2026-08-10T12:05:00Z"),
            ("human-only", "2026-08-10T12:05:00Z"),
            ("wrong-order", "2026-08-10T12:05:00Z"),
            ("expired", "2026-08-11T01:00:00Z"),
        ):
            _create_event(
                team=self.team,
                event="completed_signup",
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties={},
            )
        flush_persons_and_events()

        row = self._first_row(
            self._run(
                WebAgentAnalyticsQueryType.OVERVIEW,
                conversion_goal=CustomEventConversionGoal(customEventName="completed_signup"),
            )
        )

        self.assertEqual(row["converted_agents"], 1)

    def test_issues_group_normalized_variants_and_exclude_noise(self) -> None:
        for distinct_id in ("assistant", "human"):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={})

        self._create_http_event("assistant", "/docs/sdk-2.4.1.md", 404)
        self._create_http_event("assistant", "/docs/sdk-3.0.0.html", 404)
        self._create_http_event("assistant", "/Docs/SDK-4.0.0", 404)
        self._create_http_event("assistant", "/missing.svg", 404)
        self._create_http_event("human", "/docs/sdk-4.0.0", 404, user_agent=HUMAN_USER_AGENT)
        flush_persons_and_events()

        rows = self._rows(self._run(WebAgentAnalyticsQueryType.ISSUES))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["intent_key"], "example.com/docs/sdk")
        self.assertEqual(rows[0]["demand"], 2)
        self.assertEqual(rows[0]["variants"], 2)
        self.assertEqual(rows[1]["intent_key"], "example.com/Docs/SDK")

    def test_exact_grouping_keeps_each_requested_url_separate(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["assistant"], properties={})
        self._create_http_event("assistant", "/docs/sdk-2.4.1.md", 404)
        self._create_http_event("assistant", "/docs/sdk-3.0.0.html", 404)
        flush_persons_and_events()

        rows = self._rows(self._run(WebAgentAnalyticsQueryType.ISSUES, content_grouping=WebAgentContentGrouping.EXACT))

        self.assertEqual(
            {row["intent_path"] for row in rows},
            {"/docs/sdk-2.4.1.md", "/docs/sdk-3.0.0.html"},
        )

    def test_malformed_paths_are_counted_as_malformed_and_not_as_content_gaps(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["assistant"], properties={})
        self._create_http_event("assistant", "/docs/null", 404)
        self._create_http_event("assistant", "/docs/undefined", 404)
        self._create_http_event("assistant", "/docs/sdk-2.4.1.md", 404)
        flush_persons_and_events()

        issue_paths = {row["intent_path"] for row in self._rows(self._run(WebAgentAnalyticsQueryType.ISSUES))}
        overview = self._first_row(self._run(WebAgentAnalyticsQueryType.OVERVIEW))

        self.assertEqual(issue_paths, {"/docs/sdk"})
        self.assertEqual(overview["malformed"], 2)

    def test_issue_variants_return_only_exact_paths_for_the_selected_intent(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["assistant"], properties={})
        self._create_http_event("assistant", "/docs/sdk-2.4.1.md", 404)
        self._create_http_event("assistant", "/docs/sdk-2.4.1.md", 404)
        self._create_http_event("assistant", "/docs/sdk-3.0.0.html", 404)
        self._create_http_event("assistant", "/Docs/SDK-4.0.0", 404)
        flush_persons_and_events()

        rows = self._rows(self._run(WebAgentAnalyticsQueryType.ISSUE_VARIANTS, intent_key="example.com/docs/sdk"))

        self.assertEqual(
            {row["variant"]: row["demand"] for row in rows},
            {"/docs/sdk-2.4.1.md": 2, "/docs/sdk-3.0.0.html": 1},
        )

    def test_demand_counts_successful_agent_requests_per_exact_page(self) -> None:
        for distinct_id in ("assistant", "human"):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={})

        self._create_http_event("assistant", "/docs/start", 200)
        self._create_http_event("assistant", "/docs/start", 200)
        self._create_http_event("assistant", "/docs/other", 200)
        self._create_http_event("assistant", "/docs/missing", 404)
        self._create_http_event("assistant", "/logo.svg", 200)
        self._create_http_event("human", "/docs/start", 200, user_agent=HUMAN_USER_AGENT)
        flush_persons_and_events()

        rows = self._rows(self._run(WebAgentAnalyticsQueryType.DEMAND))

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows[0], {"page": "example.com/docs/start", "host": "example.com", "path": "/docs/start", "demand": 2}
        )
        self.assertEqual(rows[1]["page"], "example.com/docs/other")
        self.assertEqual(rows[1]["demand"], 1)

    def test_server_requests_and_client_navigations_are_counted_separately(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["assistant"], properties={})
        self._create_http_event("assistant", "/docs/start", 200)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="assistant",
            timestamp="2026-08-10T12:00:01Z",
            properties={
                "$host": "example.com",
                "$pathname": "/docs/start",
                "$raw_user_agent": ASSISTANT_USER_AGENT,
            },
        )
        flush_persons_and_events()

        row = self._first_row(self._run(WebAgentAnalyticsQueryType.OVERVIEW))

        self.assertEqual(row["active_clients"], 1)
        self.assertEqual(row["server_requests"], 1)
        self.assertEqual(row["client_navigations"], 1)

    def test_shared_property_filters_apply_to_agent_tables(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["assistant"], properties={})
        self._create_http_event("assistant", "/included", 200, host="docs.example.com")
        self._create_http_event("assistant", "/excluded", 200, host="other.example.com")
        flush_persons_and_events()

        response = self._run(
            WebAgentAnalyticsQueryType.PAGE_REQUESTS,
            properties=[EventPropertyFilter(key="$host", value="docs.example.com", operator=PropertyOperator.EXACT)],
        )

        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0][0], "docs.example.com/included")

    def test_transitions_require_the_loaded_source_page_host_and_time_window(self) -> None:
        for distinct_id in ("valid", "late", "wrong-host", "cross-domain"):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={})

        self._create_http_event("valid", "/ai/llms.txt", 200, host="docs.example.com")
        self._create_http_event(
            "valid", "/guides/start", 200, host="docs.example.com", timestamp="2026-08-10T12:05:00Z"
        )
        self._create_http_event("late", "/ai/llms.txt", 200, host="docs.example.com")
        self._create_http_event("late", "/guides/late", 200, host="docs.example.com", timestamp="2026-08-10T13:00:00Z")
        self._create_http_event("wrong-host", "/ai/llms.txt", 200, host="other.example.com")
        self._create_http_event(
            "wrong-host", "/guides/wrong-host", 200, host="other.example.com", timestamp="2026-08-10T12:05:00Z"
        )
        self._create_http_event("cross-domain", "/ai/llms.txt", 200, host="docs.example.com")
        self._create_http_event(
            "cross-domain", "/guides/cross-domain", 200, host="other.example.com", timestamp="2026-08-10T12:05:00Z"
        )
        flush_persons_and_events()

        response = self._run(
            WebAgentAnalyticsQueryType.TRANSITIONS, llms_txt_url="https://docs.example.com/ai/llms.txt"
        )

        self.assertEqual(response.results, [["/guides/start", 1, 0]])

    def test_result_limit_reports_more_rows_without_silently_dropping_the_signal(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["assistant"], properties={})
        self._create_http_event("assistant", "/one", 404)
        self._create_http_event("assistant", "/two", 404)
        flush_persons_and_events()

        response = self._run(WebAgentAnalyticsQueryType.ISSUES, limit=1)

        self.assertEqual(len(response.results), 1)
        self.assertTrue(response.hasMore)
        self.assertEqual(response.limit, 1)

    def test_page_requests_counts_format_mix_per_client(self) -> None:
        for distinct_id in ("paired", "html-only", "markdown-only"):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], properties={})

        self._create_http_event("paired", "/docs/start", 200)
        self._create_http_event("paired", "/docs/start.md", 200)
        self._create_http_event("html-only", "/docs/start", 200)
        self._create_http_event("markdown-only", "/docs/other.md", 200)
        flush_persons_and_events()

        rows = self._rows(self._run(WebAgentAnalyticsQueryType.PAGE_REQUESTS))

        self.assertEqual(
            rows[0],
            {
                "page": "example.com/docs/start",
                "fetches": 3,
                "md_fetches": 1,
                "html_fetches": 2,
                "paired_clients": 1,
            },
        )

    def test_journeys_split_on_inactivity_and_keep_hosts_separate(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["wanderer"], properties={})

        self._create_http_event("wanderer", "/p1", 200, timestamp="2026-08-10T12:00:00Z")
        self._create_http_event("wanderer", "/p2", 200, timestamp="2026-08-10T12:05:00Z")
        self._create_http_event("wanderer", "/p3", 200, timestamp="2026-08-10T13:00:00Z")
        self._create_http_event("wanderer", "/q1", 200, host="other.com", timestamp="2026-08-10T12:02:00Z")
        flush_persons_and_events()

        journeys = self._rows(self._run(WebAgentAnalyticsQueryType.JOURNEYS))
        summary = self._first_row(self._run(WebAgentAnalyticsQueryType.JOURNEY_SUMMARY))

        self.assertEqual(len(journeys), 3)
        self.assertEqual(summary["total_journeys"], 3)
        self.assertEqual(sorted(str(row["host"]) for row in journeys), ["example.com", "example.com", "other.com"])
        example_requests = sorted(
            (int(str(row["requests"])) for row in journeys if row["host"] == "example.com"), reverse=True
        )
        self.assertEqual(example_requests, [2, 1])

    def test_journey_keys_are_opaque_and_survive_a_widened_date_range(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["wanderer"], properties={})
        self._create_http_event("wanderer", "/early", 200, timestamp="2026-08-02T09:00:00Z")
        self._create_http_event("wanderer", "/late", 200, timestamp="2026-08-10T12:00:00Z")
        flush_persons_and_events()

        narrow = self._rows(self._run(WebAgentAnalyticsQueryType.JOURNEYS, date_from="2026-08-05"))
        wide = self._rows(self._run(WebAgentAnalyticsQueryType.JOURNEYS, date_from="2026-08-01"))

        self.assertEqual(len(narrow), 1)
        self.assertEqual(len(wide), 2)
        late_key = narrow[0]["journey_key"]
        self.assertIn(late_key, [row["journey_key"] for row in wide])
        for row in wide:
            key = str(row["journey_key"])
            self.assertNotIn("wanderer", key)
            self.assertNotIn("example.com", key)

        detail = self._rows(
            self._run(
                WebAgentAnalyticsQueryType.JOURNEY_DETAIL,
                journey_key=str(late_key),
                date_from="2026-08-01",
            )
        )
        self.assertEqual([row["path"] for row in detail], ["/late"])

    def test_journey_detail_labels_transitions_by_the_strongest_available_signal(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["reader"], properties={})
        self._create_http_event("reader", "/docs", 200, timestamp="2026-08-10T12:00:00Z")
        self._create_http_event(
            "reader",
            "/guide",
            200,
            referrer="https://example.com/docs",
            timestamp="2026-08-10T12:00:10Z",
        )
        self._create_http_event("reader", "/pricing", 200, timestamp="2026-08-10T12:00:20Z")
        flush_persons_and_events()

        journeys = self._rows(self._run(WebAgentAnalyticsQueryType.JOURNEYS))
        self.assertEqual(len(journeys), 1)
        detail = self._rows(
            self._run(WebAgentAnalyticsQueryType.JOURNEY_DETAIL, journey_key=str(journeys[0]["journey_key"]))
        )

        self.assertEqual([row["path"] for row in detail], ["/docs", "/guide", "/pricing"])
        self.assertEqual([row["transition"] for row in detail], ["start", "confirmed", "sequential"])

        limited_detail = self._rows(
            self._run(
                WebAgentAnalyticsQueryType.JOURNEY_DETAIL,
                journey_key=str(journeys[0]["journey_key"]),
                limit=2,
            )
        )
        self.assertEqual([row["path"] for row in limited_detail], ["/docs", "/guide"])

    def test_journey_detail_marks_same_timestamp_requests_as_parallel(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["reader"], properties={})
        self._create_http_event("reader", "/x", 200, timestamp="2026-08-10T12:00:00Z")
        self._create_http_event("reader", "/y", 200, timestamp="2026-08-10T12:00:00Z")
        flush_persons_and_events()

        journeys = self._rows(self._run(WebAgentAnalyticsQueryType.JOURNEYS))
        detail = self._rows(
            self._run(WebAgentAnalyticsQueryType.JOURNEY_DETAIL, journey_key=str(journeys[0]["journey_key"]))
        )

        self.assertEqual(len(detail), 2)
        self.assertEqual(sorted(str(row["transition"]) for row in detail), ["parallel", "start"])

    def test_request_anatomy_aggregates_format_retries_and_errors_per_agent(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["client"], properties={})
        self._create_http_event("client", "/docs", 200, timestamp="2026-08-10T12:00:00Z")
        self._create_http_event("client", "/docs.md", 200, timestamp="2026-08-10T12:00:05Z")
        self._create_http_event("client", "/missing", 404, timestamp="2026-08-10T12:00:10Z")
        self._create_http_event("client", "/before.md", 200, timestamp="2026-08-10T12:00:15Z")
        self._create_http_event("client", "/before", 200, timestamp="2026-08-10T12:00:20Z")
        flush_persons_and_events()

        rows = self._rows(self._run(WebAgentAnalyticsQueryType.REQUEST_ANATOMY))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requests"], 5)
        self.assertEqual(rows[0]["requested_markdown"], 2)
        self.assertEqual(rows[0]["retry_pairs"], 1)
        self.assertEqual(rows[0]["errors"], 1)

    def test_every_query_mode_compiles(self) -> None:
        for query_type in WebAgentAnalyticsQueryType:
            with self.subTest(query_type=query_type):
                query = WebAgentAnalyticsQuery(
                    queryType=query_type,
                    dateRange=DateRange(date_from="2026-08-01", date_to="2026-08-20"),
                    intentKey="example.com/docs/sdk"
                    if query_type == WebAgentAnalyticsQueryType.ISSUE_VARIANTS
                    else None,
                    journeyKey="client:ChatGPT:example.com:1"
                    if query_type == WebAgentAnalyticsQueryType.JOURNEY_DETAIL
                    else None,
                    properties=[],
                )
                runner = WebAgentAnalyticsQueryRunner(team=self.team, query=query)
                context = HogQLContext(
                    team=self.team,
                    team_id=self.team.pk,
                    enable_select_queries=True,
                    modifiers=runner.modifiers,
                )
                sql, _ = prepare_and_print_ast(runner.to_query(), context=context, dialect="clickhouse")

                self.assertLess(len(sql), 1_048_576)
