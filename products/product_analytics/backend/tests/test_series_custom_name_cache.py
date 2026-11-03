import json
from typing import Any

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    CachedLifecycleQueryResponse,
    CachedStickinessQueryResponse,
    CachedTrendsQueryResponse,
    EventsNode,
    LifecycleQuery,
    LifecycleQueryResponse,
    StickinessQuery,
    StickinessQueryResponse,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog.hogql_queries.query_runner import ExecutionMode, QueryRunner

from products.product_analytics.backend.hogql_queries.lifecycle.lifecycle_query_runner import LifecycleQueryRunner
from products.product_analytics.backend.hogql_queries.stickiness.stickiness_query_runner import StickinessQueryRunner
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

RENAMED = {"custom_name": "Renamed"}
FORMULA = {"trendsFilter": TrendsFilter(formulaNodes=[TrendsFormulaNode(formula="A", custom_name="Total")])}


class TestSeriesCustomNameCache(BaseTest):
    @parameterized.expand(
        [
            ("trends", TrendsQueryRunner, TrendsQuery, TrendsQueryResponse, {}, {}, RENAMED, None, "Renamed", False),
            (
                "trends_cleared_custom_name_falls_back_to_name",
                TrendsQueryRunner,
                TrendsQuery,
                TrendsQueryResponse,
                {},
                {"name": "Views", "custom_name": "Old"},
                {"name": "Views"},
                "Old",
                "Views",
                False,
            ),
            (
                "trends_name_matching_the_event_serves_raw",
                TrendsQueryRunner,
                TrendsQuery,
                TrendsQueryResponse,
                {},
                {"name": "$pageview"},
                {"name": "$pageview"},
                None,
                None,
                True,
            ),
            (
                "stickiness",
                StickinessQueryRunner,
                StickinessQuery,
                StickinessQueryResponse,
                {},
                {},
                RENAMED,
                None,
                "Renamed",
                False,
            ),
            (
                "lifecycle",
                LifecycleQueryRunner,
                LifecycleQuery,
                LifecycleQueryResponse,
                {},
                {},
                RENAMED,
                None,
                "Renamed",
                False,
            ),
            (
                "trends_formula_keeps_the_formula_name_and_serves_raw",
                TrendsQueryRunner,
                TrendsQuery,
                TrendsQueryResponse,
                FORMULA,
                {},
                RENAMED,
                "Total",
                "Total",
                True,
            ),
        ]
    )
    def test_raw_cache_read_patches_a_series_renamed_after_caching(
        self,
        _name: str,
        runner_class: type[QueryRunner],
        query_class: type[TrendsQuery | StickinessQuery | LifecycleQuery],
        response_class: type[TrendsQueryResponse | StickinessQueryResponse | LifecycleQueryResponse],
        query_kwargs: dict[str, Any],
        cached_series: dict[str, str],
        current_series: dict[str, str],
        cached_custom_name: str | None,
        expected_custom_name: str | None,
        served_raw: bool,
    ) -> None:
        cached_rows = [{"order": 0, "custom_name": cached_custom_name, "data": [1]}]
        with mock.patch.object(runner_class, "calculate", return_value=response_class(results=cached_rows)):
            runner_class(
                query=query_class(series=[EventsNode(event="$pageview", **cached_series)], **query_kwargs),
                team=self.team,
            ).run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        runner = runner_class(
            query=query_class(series=[EventsNode(event="$pageview", **current_series)], **query_kwargs),
            team=self.team,
        )
        runner.serve_raw_cached_results = True
        response = runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)

        assert isinstance(
            response, CachedTrendsQueryResponse | CachedStickinessQueryResponse | CachedLifecycleQueryResponse
        )
        raw_results = runner.raw_cached_results_bytes
        assert (raw_results is not None) == served_raw
        results = json.loads(raw_results) if raw_results is not None else response.results
        assert [row["custom_name"] for row in results] == [expected_custom_name]
