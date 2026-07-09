from typing import cast

from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import WebAnalyticsPreComputeStrategy, WebStatsBreakdown

from posthog.clickhouse.query_tagging import (
    Feature,
    Product,
    create_base_tags,
    get_query_tag_value,
    query_tags,
    tag_queries,
)

from products.web_analytics.backend.hogql_queries.metrics import (
    WEB_ANALYTICS_QUERY_COUNTER,
    WEB_ANALYTICS_QUERY_DURATION,
    WEB_ANALYTICS_QUERY_ERRORS,
)
from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_REJECTED,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    can_use_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner


def _make_runner(
    query_kind: str = "WebStatsTableQuery",
    breakdown: WebStatsBreakdown | None = WebStatsBreakdown.PAGE,
    conversion_goal: object | None = None,
    sampling: object | None = None,
    properties: list | None = None,
    query_strategy: str | None = None,
) -> WebAnalyticsQueryRunner:
    """Build a WebAnalyticsQueryRunner with a fake query, team, and date range."""
    query = MagicMock()
    query.kind = query_kind
    query.breakdownBy = breakdown
    query.conversionGoal = conversion_goal
    query.sampling = sampling
    query.properties = properties or []

    team = MagicMock()
    team.pk = 42
    team.organization_id = "org_abc"

    runner = MagicMock(spec=WebAnalyticsQueryRunner)
    runner.query = query
    runner.team = team
    # The real `filters_eligibility_hash` is an Optional[str] cached_property; `spec` doesn't
    # propagate the annotation so MagicMock would return a Mock object which fails
    # the QueryTags pydantic validation in `tag_queries`. Pin a stable test value.
    runner.filters_eligibility_hash = "test_filters_eligibility_hash"
    cast(MagicMock, runner.query_strategy).return_value = query_strategy
    cast(MagicMock, runner.clickhouse_query_type).return_value = (
        f"{query_strategy}_query" if query_strategy is not None else None
    )

    date_range = MagicMock()
    date_range.date_from_str = "2024-01-01"
    date_range.date_to_str = "2024-01-07"
    runner.query_date_range = date_range

    return runner


def _get_counter_value(metric, label_filter: dict) -> float:
    """Get the _total value for a prometheus Counter matching the given labels."""
    for sample in metric.collect()[0].samples:
        if not sample.name.endswith("_total"):
            continue
        if all(sample.labels.get(k) == v for k, v in label_filter.items()):
            return sample.value
    return 0.0


def _get_histogram_count(metric, label_filter: dict) -> float:
    """Get the _count value for a prometheus Histogram matching the given labels."""
    for sample in metric.collect()[0].samples:
        if not sample.name.endswith("_count"):
            continue
        if all(sample.labels.get(k) == v for k, v in label_filter.items()):
            return sample.value
    return 0.0


class TestWebAnalyticsMetrics(TestCase):
    def setUp(self):
        # Clear all prometheus metrics before each test to avoid cross-test leakage
        WEB_ANALYTICS_QUERY_COUNTER._metrics.clear()
        WEB_ANALYTICS_QUERY_DURATION._metrics.clear()
        WEB_ANALYTICS_QUERY_ERRORS._metrics.clear()
        WEB_ANALYTICS_LAZY_PRECOMPUTE_REJECTED._metrics.clear()
        WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK._metrics.clear()
        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS._metrics.clear()
        # Reset `query_tags` ContextVar — it persists across tests in the same
        # process and `tag_queries` only updates fields explicitly passed in,
        # so a prior test's `breakdown_by` would leak into a runner whose
        # query has no breakdown.
        query_tags.set(create_base_tags())

    @parameterized.expand(
        [
            (
                "stats_table_page",
                "WebStatsTableQuery",
                WebStatsBreakdown.PAGE,
                None,
                {
                    "query_kind": "WebStatsTableQuery",
                    "query_strategy": "stats_table_simple_breakdown",
                    "breakdown": "Page",
                    "has_conversion_goal": "false",
                },
                "stats_table_simple_breakdown",
            ),
            (
                "overview",
                "WebOverviewQuery",
                None,
                None,
                {
                    "query_kind": "WebOverviewQuery",
                    "query_strategy": "none",
                    "breakdown": "none",
                    "has_conversion_goal": "false",
                },
                None,
            ),
            (
                "stats_table_with_conversion",
                "WebStatsTableQuery",
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                MagicMock(),
                {
                    "query_kind": "WebStatsTableQuery",
                    "query_strategy": "stats_table_channel_type",
                    "breakdown": "InitialChannelType",
                    "has_conversion_goal": "true",
                },
                "stats_table_channel_type",
            ),
        ],
    )
    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value",
        return_value="user_123",
    )
    def test_successful_query_emits_correct_labels(
        self, _name, query_kind, breakdown, conversion_goal, expected_labels, query_strategy, _mock_tag
    ):
        runner = _make_runner(
            query_kind=query_kind,
            breakdown=breakdown,
            conversion_goal=conversion_goal,
            query_strategy=query_strategy,
        )

        fake_response = MagicMock()
        fake_response.preComputeStrategy = WebAnalyticsPreComputeStrategy.PRE_AGGREGATED

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        label_filter = {**expected_labels, "pre_compute_strategy": "pre_aggregated"}
        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, label_filter) == 1.0

    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_error_query_increments_error_counter(self, _mock_tag):
        runner = _make_runner(
            query_kind="WebStatsTableQuery",
            breakdown=WebStatsBreakdown.BROWSER,
            query_strategy="stats_table_simple_breakdown",
        )

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                WebAnalyticsQueryRunner.calculate(runner)

        error_filter = {
            "query_kind": "WebStatsTableQuery",
            "query_strategy": "stats_table_simple_breakdown",
            "breakdown": "Browser",
            "error_type": "ValueError",
        }
        assert _get_counter_value(WEB_ANALYTICS_QUERY_ERRORS, error_filter) == 1.0

        counter_filter = {
            "query_kind": "WebStatsTableQuery",
            "query_strategy": "stats_table_simple_breakdown",
            "pre_compute_strategy": "unknown",
        }
        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, counter_filter) == 1.0

    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value",
        return_value="user_456",
    )
    def test_canonical_log_line_emitted(self, _mock_tag):
        runner = _make_runner(query_kind="WebOverviewQuery", breakdown=None, properties=["fake_prop"])

        fake_response = MagicMock()
        fake_response.preComputeStrategy = WebAnalyticsPreComputeStrategy.LIVE

        with (
            patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response),
            patch("products.web_analytics.backend.hogql_queries.web_analytics_query_runner.logger") as mock_logger,
        ):
            WebAnalyticsQueryRunner.calculate(runner)

        canonical_calls = [c for c in mock_logger.info.call_args_list if c[0] and c[0][0] == "web_analytics_query"]
        assert len(canonical_calls) == 1
        kw = canonical_calls[0][1]
        assert kw["team_id"] == 42
        assert kw["organization_id"] == "org_abc"
        assert kw["user_id"] == "user_456"
        assert kw["query_kind"] == "WebOverviewQuery"
        assert kw["query_strategy"] is None
        assert kw["clickhouse_query_type"] is None
        assert kw["breakdown"] == "none"
        assert kw["pre_compute_strategy"] == "live"
        assert kw["error"] is False
        assert kw["error_type"] is None
        assert kw["filter_count"] == 1
        assert kw["date_from"] == "2024-01-01"
        assert kw["date_to"] == "2024-01-07"

    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_stats_table_log_line_includes_query_strategy(self, _mock_tag):
        runner = _make_runner(query_kind="WebStatsTableQuery", breakdown=WebStatsBreakdown.PAGE)
        cast(MagicMock, runner.query_strategy).return_value = "stats_table_path_bounce"
        cast(MagicMock, runner.clickhouse_query_type).return_value = "stats_table_path_bounce_query"

        fake_response = MagicMock()
        fake_response.preComputeStrategy = WebAnalyticsPreComputeStrategy.LIVE

        with (
            patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response),
            patch("products.web_analytics.backend.hogql_queries.web_analytics_query_runner.logger") as mock_logger,
        ):
            WebAnalyticsQueryRunner.calculate(runner)

        assert mock_logger.info.call_args[1]["query_strategy"] == "stats_table_path_bounce"
        assert mock_logger.info.call_args[1]["clickhouse_query_type"] == "stats_table_path_bounce_query"

    @parameterized.expand([(b.name, b) for b in WebStatsBreakdown])
    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_all_breakdown_values_produce_valid_labels(self, _name, breakdown, _mock_tag):
        runner = _make_runner(breakdown=breakdown)
        fake_response = MagicMock()
        fake_response.preComputeStrategy = None

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        label_filter = {"breakdown": breakdown.value}
        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, label_filter) >= 1.0

    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_pre_compute_strategy_none_maps_to_unknown(self, _mock_tag):
        runner = _make_runner()
        fake_response = MagicMock()
        fake_response.preComputeStrategy = None

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        assert (
            _get_counter_value(
                WEB_ANALYTICS_QUERY_COUNTER,
                {"query_strategy": "none", "pre_compute_strategy": "unknown"},
            )
            == 1.0
        )

    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_response_missing_pre_compute_strategy_attr_maps_to_unknown(self, _mock_tag):
        runner = _make_runner()
        fake_response = MagicMock(spec=[])  # empty spec = no attributes

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        assert (
            _get_counter_value(
                WEB_ANALYTICS_QUERY_COUNTER,
                {"query_strategy": "none", "pre_compute_strategy": "unknown"},
            )
            == 1.0
        )

    @parameterized.expand(
        [
            # (name, query_kind, breakdown_with_value_or_none, expect_breakdown_by_tag)
            ("overview_no_breakdown", "WebOverviewQuery", None, None),
            ("stats_table_page", "WebStatsTableQuery", WebStatsBreakdown.PAGE, ["Page"]),
            ("stats_table_browser", "WebStatsTableQuery", WebStatsBreakdown.BROWSER, ["Browser"]),
            (
                "stats_table_initial_channel",
                "WebStatsTableQuery",
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                ["InitialChannelType"],
            ),
            ("goals", "WebGoalsQuery", None, None),
            ("external_clicks", "WebExternalClicksTableQuery", None, None),
            ("vitals_paths", "WebVitalsPathBreakdownQuery", None, None),
        ],
    )
    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_tag_queries_payload_consistent_across_runners(
        self, _name, query_kind, breakdown, expect_breakdown_by_tag, _mock_tag
    ):
        """Every web analytics query runner must land the same shape in
        `system.query_log.log_comment` via `tag_queries` — `product`,
        `feature`, `query`, and `breakdown_by` (when the query has a
        `breakdownBy`). Drift here breaks downstream `query_log`-based
        analysis (per-strategy latency, per-tile cost slicing).

        `filters_eligibility_hash` is **not** in this payload — it stays on
        the structlog contextvar only, see
        `test_filters_eligibility_hash_not_in_query_tags`."""
        runner = _make_runner(query_kind=query_kind, breakdown=breakdown)
        # The real `WebQueryNode.model_dump(mode="json")` returns a dict; the
        # MagicMock-backed `query` returns another Mock by default, which
        # bypasses the dict-shape assertion below.
        cast(MagicMock, runner.query.model_dump).return_value = {"kind": query_kind}

        fake_response = MagicMock()
        fake_response.preComputeStrategy = WebAnalyticsPreComputeStrategy.LIVE

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        assert get_query_tag_value("product") == Product.WEB_ANALYTICS
        assert get_query_tag_value("feature") == Feature.QUERY
        # `query` is the dumped query payload — a dict with at least `kind`.
        query_tag = get_query_tag_value("query")
        assert isinstance(query_tag, dict) and query_tag.get("kind") == query_kind
        assert get_query_tag_value("breakdown_by") == expect_breakdown_by_tag

    @parameterized.expand(
        [
            ("web_overview", "web_overview"),
            ("web_stats", "web_stats"),
        ]
    )
    def test_lazy_precompute_gate_rejection_increments_counter(self, _name, family):
        runner = MagicMock()
        runner.team = MagicMock(pk=42, uuid="00000000-0000-0000-0000-000000000000", organization_id=7, id=42)
        runner.query = MagicMock(useWebAnalyticsPrecompute=True)

        with patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            assert can_use_lazy_precompute(runner, log_prefix=family) is False

        assert (
            _get_counter_value(
                WEB_ANALYTICS_LAZY_PRECOMPUTE_REJECTED,
                {"family": family, "reason": "OrgFeatureFlagDisabled"},
            )
            == 1.0
        )

    @parameterized.expand(
        [
            ("web_overview", "web_overview"),
            ("web_stats", "web_stats"),
        ]
    )
    def test_lazy_precompute_per_query_opt_in_not_set_rejection(self, _name, family):
        runner = MagicMock()
        runner.team = MagicMock(pk=42, uuid="00000000-0000-0000-0000-000000000000", organization_id=7, id=42)
        runner.query = MagicMock(useWebAnalyticsPrecompute=False)

        with patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            assert can_use_lazy_precompute(runner, log_prefix=family) is False

        assert (
            _get_counter_value(
                WEB_ANALYTICS_LAZY_PRECOMPUTE_REJECTED,
                {"family": family, "reason": "PerQueryOptInNotSet"},
            )
            == 1.0
        )

    @parameterized.expand(
        [
            ("empty_range",),
            ("no_job_ids",),
            ("current_not_ready",),
            ("previous_not_ready",),
        ]
    )
    def test_lazy_precompute_fallback_counter_label_space(self, reason):
        # Verifies the metric accepts each `reason` value the lazy modules emit.
        # Integration coverage of the actual call sites lives in the per-runner
        # lazy precompute tests; this test is a fast guard against label drift.
        WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family="web_overview", reason=reason).inc()
        WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family="web_stats", reason=reason).inc()

        assert (
            _get_counter_value(
                WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
                {"family": "web_overview", "reason": reason},
            )
            == 1.0
        )
        assert (
            _get_counter_value(
                WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
                {"family": "web_stats", "reason": reason},
            )
            == 1.0
        )

    @parameterized.expand([("web_overview",), ("web_stats",)])
    def test_lazy_precompute_success_counter_label_space(self, family):
        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=family).inc()
        assert _get_counter_value(WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS, {"family": family}) == 1.0

    @parameterized.expand(
        [
            ("no_prior_tag", None),
            (
                "overwrites_wrapper_payload",
                {"kind": "InsightVizNode", "source": {"kind": "WebOverviewQuery"}},
            ),
            (
                "overwrites_prior_runner_payload",
                {"kind": "WebOverviewQuery", "dateRange": {"date_from": "-30d"}},
            ),
        ]
    )
    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_calculate_tags_inner_query_payload(self, _name, prior_tag, _mock_tag):
        query_tags.set(create_base_tags())
        if prior_tag is not None:
            tag_queries(query=prior_tag)

        runner = _make_runner(query_kind="WebOverviewQuery", breakdown=None)
        expected_payload = {"kind": "WebOverviewQuery", "dateRange": {"date_from": "-7d", "date_to": None}}
        cast(MagicMock, runner.query.model_dump).return_value = expected_payload

        fake_response = MagicMock()
        fake_response.preComputeStrategy = WebAnalyticsPreComputeStrategy.LIVE
        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        self.assertEqual(get_query_tag_value("query"), expected_payload)

    @patch(
        "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.get_query_tag_value", return_value=None
    )
    def test_strategy_resolution_failure_still_emits_error_metrics(self, _mock_tag):
        runner = _make_runner(query_kind="WebStatsTableQuery", breakdown=WebStatsBreakdown.PAGE)
        cast(MagicMock, runner.query_strategy).side_effect = RuntimeError("strategy boom")
        cast(MagicMock, runner.clickhouse_query_type).side_effect = RuntimeError("strategy boom")

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                WebAnalyticsQueryRunner.calculate(runner)

        assert (
            _get_counter_value(
                WEB_ANALYTICS_QUERY_ERRORS,
                {
                    "query_kind": "WebStatsTableQuery",
                    "query_strategy": "strategy_resolution_failed",
                    "breakdown": "Page",
                    "error_type": "ValueError",
                },
            )
            == 1.0
        )
