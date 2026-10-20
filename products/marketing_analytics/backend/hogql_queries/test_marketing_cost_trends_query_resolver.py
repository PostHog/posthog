from datetime import UTC, datetime

import time_machine
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    CompareFilter,
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    DateRange,
    EventsNode,
    HogQLQueryModifiers,
    MarketingAnalyticsCostFallback,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    TrendsQuery,
)

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationExecutor,
    LazyComputationResult,
    compute_query_hash,
    ensure_precomputed,
)
from products.marketing_analytics.backend.hogql_queries.adapters.base import (
    GoogleAdsConfig,
    MarketingSourceAdapter,
    QueryContext,
)
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.adapters.google_ads import GoogleAdsAdapter
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_cost_trends_query_resolver import (
    MarketingCostTrendsQueryResolver,
)
from products.marketing_analytics.dags.marketing_precompute import _ensure_costs_for_team
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

MODULE = "products.marketing_analytics.backend.hogql_queries.marketing_cost_trends_query_resolver"


@time_machine.travel("2025-01-15T12:00:00Z", tick=False)
class TestMarketingCostTrendsQueryResolver(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team(id=17, timezone="America/New_York", base_currency="USD")
        self.live_series = [
            DataWarehouseNode(
                id=f"source_{source}_stats",
                table_name=f"source_{source}_stats",
                id_field="id",
                distinct_id_field="id",
                timestamp_field="date",
            )
            for source in ("a", "b")
        ]
        self.query = TrendsQuery(
            interval="day",
            dateRange=DateRange(date_from="2025-01-10", date_to="2025-01-12"),
            compareFilter=CompareFilter(compare=True),
            series=[
                DataWarehouseNode(
                    id="marketing_costs_precomputed",
                    table_name="marketing_costs_precomputed",
                    id_field="campaign_id",
                    distinct_id_field="campaign_id",
                    timestamp_field="timestamp",
                )
            ],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(type="data_warehouse", property="source_name")]),
            marketingAnalyticsCostFallback=MarketingAnalyticsCostFallback(
                series=self.live_series, sourceIds=["a", "b"]
            ),
        )
        self.adapters = []
        for source_id in ("a", "b"):
            adapter = Mock(spec=MarketingSourceAdapter)
            adapter.get_source_id.return_value = source_id
            adapter.supports_level.return_value = True
            adapter.build_materialization_query.return_value = ast.SelectQuery(select=[ast.Constant(value=source_id)])
            self.adapters.append(adapter)
        self.factory = self.enterContext(patch(f"{MODULE}.MarketingSourceFactory"))
        self.factory.return_value.get_valid_adapters.return_value = self.adapters
        self.factory.return_value.build_materialization_queries.side_effect = (
            MarketingSourceFactory.build_materialization_queries
        )
        self.database = Mock()
        self.ensure = self.enterContext(patch(f"{MODULE}.ensure_precomputed"))
        self.config = self.enterContext(patch(f"{MODULE}.MarketingAnalyticsConfig.from_team"))
        self.config.return_value = MarketingAnalyticsConfig(costs_precomputation_enabled=True)

    def runner(self) -> MarketingCostTrendsQueryResolver:
        current = QueryDateRange(
            date_range=self.query.dateRange, team=self.team, interval=self.query.interval, now=datetime.now()
        )
        ranges = [current]
        if self.query.compareFilter and self.query.compareFilter.compare:
            previous = (
                QueryCompareToDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=self.query.interval,
                    now=datetime.now(),
                    compare_to=self.query.compareFilter.compare_to,
                    full_comparison_period=True,
                )
                if self.query.compareFilter.compare_to
                else QueryPreviousPeriodDateRange(
                    date_range=self.query.dateRange,
                    team=self.team,
                    interval=self.query.interval,
                    now=datetime.now(),
                    full_comparison_period=True,
                )
            )
            ranges.append(previous)
        return MarketingCostTrendsQueryResolver(self.query.model_copy(deep=True), self.team, ranges, self.database)

    @parameterized.expand(
        [
            ("flag_off", False, [True, True, True, True], False),
            ("current_source_missing", True, [True, False], False),
            ("comparison_source_missing", True, [True, True, True, False], False),
            ("complete_including_empty_windows", True, [True, True, True, True], True),
            ("custom_comparison", True, [True, True, True, True], True),
        ]
    )
    def test_selects_precomputed_only_for_complete_coverage(
        self, _name: str, enabled: bool, coverage: list[bool], precomputed: bool
    ) -> None:
        self.config.return_value.costs_precomputation_enabled = enabled
        if _name == "custom_comparison":
            self.query.compareFilter = CompareFilter(compare=True, compare_to="-1y")
        self.ensure.side_effect = [LazyComputationResult(ready=ready, job_ids=[]) for ready in coverage]
        runner = self.runner()
        result = runner.resolve_query()
        assert result.marketingAnalyticsCostFallback is None
        assert result.dateRange == self.query.dateRange
        assert result.compareFilter == self.query.compareFilter
        assert self.query.marketingAnalyticsCostFallback is not None
        if precomputed:
            series = result.series[0]
            assert isinstance(series, DataWarehouseNode)
            assert series.table_name == "marketing_costs_precomputed"
            assert series.properties is not None
            source_filter = series.properties[-1]
            assert isinstance(source_filter, DataWarehousePropertyFilter)
            assert source_filter.value == ["a", "b"]
            assert result.breakdownFilter == self.query.breakdownFilter
            checked_ranges = [
                (call.kwargs["time_range_start"], call.kwargs["time_range_end"]) for call in self.ensure.call_args_list
            ]
            assert checked_ranges == [
                (runner.date_ranges[0].date_from(), runner.date_ranges[0].date_to()),
                (runner.date_ranges[0].date_from(), runner.date_ranges[0].date_to()),
                (runner.date_ranges[1].date_from(), runner.date_ranges[1].date_to()),
                (runner.date_ranges[1].date_from(), runner.date_ranges[1].date_to()),
            ]
            assert runner.date_ranges[0].date_from() == datetime(2025, 1, 10, 5, tzinfo=UTC)
            if _name == "custom_comparison":
                assert runner.date_ranges[1].date_from().year == 2024
        else:
            assert result.series == self.live_series
            assert result.breakdownFilter is None
        for call in self.ensure.call_args_list:
            assert call.kwargs["run_inserts"] is False
            assert call.kwargs["stale_while_revalidate_seconds"] == 0
        if not enabled:
            self.ensure.assert_not_called()
            self.database.assert_not_called()

    @parameterized.expand([("unmaterializable",), ("check_error",), ("inaccessible_source",), ("expired",)])
    def test_uncertain_coverage_uses_live(self, case: str) -> None:
        self.ensure.return_value = LazyComputationResult(ready=True, job_ids=[])
        if case == "unmaterializable":
            self.adapters[1].build_materialization_query.return_value = None
        elif case == "check_error":
            self.ensure.side_effect = RuntimeError("Coverage service unavailable")
        elif case == "expired":
            self.ensure.return_value = LazyComputationResult(ready=True, job_ids=[], stale=True)
        else:
            assert self.query.marketingAnalyticsCostFallback is not None
            self.query.marketingAnalyticsCostFallback.sourceIds = ["b"]
            self.factory.return_value.get_valid_adapters.return_value = self.adapters[:1]
        result = self.runner().resolve_query()
        assert result.series == self.live_series
        assert result.breakdownFilter is None

    @parameterized.expand([(True,), (False,)])
    def test_only_selected_sources_and_current_period_need_coverage(self, ready: bool) -> None:
        assert self.query.marketingAnalyticsCostFallback is not None
        self.query.marketingAnalyticsCostFallback.sourceIds = ["b"]
        self.query.marketingAnalyticsCostFallback.series = self.live_series[1:]
        self.query.compareFilter = CompareFilter(compare=False)
        self.ensure.return_value = LazyComputationResult(ready=ready, job_ids=[])
        result = self.runner().resolve_query()
        if ready:
            series = result.series[0]
            assert isinstance(series, DataWarehouseNode)
            assert series.table_name == "marketing_costs_precomputed"
            assert series.properties is not None
            source_filter = series.properties[-1]
            assert isinstance(source_filter, DataWarehousePropertyFilter)
            assert source_filter.value == ["b"]
        else:
            assert result.series == self.live_series[1:]
            assert result.breakdownFilter is None
        assert self.ensure.call_count == 1
        assert self.ensure.call_args.kwargs["insert_query"].select == [ast.Constant(value="b")]

    @parameterized.expand([("replace_series",), ("add_series",)])
    def test_edited_insight_executes_requested_series(self, case: str) -> None:
        event = EventsNode(event="$pageview")
        self.query.series = [event] if case == "replace_series" else [*self.query.series, event]
        result = self.runner().resolve_query()
        assert result.series == self.query.series
        assert result.breakdownFilter == self.query.breakdownFilter
        assert result.marketingAnalyticsCostFallback is None
        self.ensure.assert_not_called()

    def test_coverage_and_warmer_hash_the_same_real_adapter(self) -> None:
        assert self.query.marketingAnalyticsCostFallback is not None
        self.query.marketingAnalyticsCostFallback.sourceIds = ["a"]
        self.query.marketingAnalyticsCostFallback.series = self.live_series[:1]
        runner = self.runner()
        adapter_config = GoogleAdsConfig(
            source_type="GoogleAds",
            source_id="a",
            campaign_table=DataWarehouseTable(name="googleads_campaign", columns={}),
            stats_table=DataWarehouseTable(name="googleads_campaign_stats", columns={}),
        )

        def initialize_factory(factory: MarketingSourceFactory, context: QueryContext) -> None:
            factory.context = context

        def create_adapters(factory: MarketingSourceFactory) -> list[MarketingSourceAdapter]:
            return [GoogleAdsAdapter(adapter_config, factory.context)]

        self.factory.side_effect = MarketingSourceFactory
        self.ensure.side_effect = ensure_precomputed
        base_module = "products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner"
        with (
            patch(
                "posthog.hogql_queries.query_runner.create_default_modifiers_for_team",
                return_value=HogQLQueryModifiers(),
            ),
            patch.object(MarketingSourceFactory, "__init__", initialize_factory),
            patch.object(MarketingSourceFactory, "create_adapters", create_adapters),
            patch(f"{base_module}.MarketingSourceFactory", MarketingSourceFactory),
            patch(f"{base_module}.marketing_ensure_precomputed", side_effect=ensure_precomputed),
            patch.object(
                LazyComputationExecutor, "execute", return_value=LazyComputationResult(ready=True, job_ids=[])
            ) as execute,
        ):
            series = runner.resolve_query().series[0]
            assert isinstance(series, DataWarehouseNode)
            assert series.table_name == "marketing_costs_precomputed"
            trend_hashes = [compute_query_hash(call.args[1]) for call in execute.call_args_list]
            execute.reset_mock()
            warmer = MarketingAnalyticsTableQueryRunner(
                query=MarketingAnalyticsTableQuery(properties=[]), team=self.team
            )
            warmer.__dict__["_shared_hogql_database"] = runner.get_database()
            for date_range in (runner.date_ranges[0], runner.date_ranges[1]):
                warmer._build_costs_from_precompute(date_range)
            warmer_hashes = [compute_query_hash(call.args[1]) for call in execute.call_args_list]
            execute.reset_mock()
            dag_module = "products.marketing_analytics.dags.marketing_precompute"
            with patch(f"{dag_module}.COST_MATERIALIZATION_GRAINS", [MarketingAnalyticsDrillDownLevel.CAMPAIGN]):
                _ensure_costs_for_team(
                    Mock(),
                    self.team,
                    runner.date_ranges[0].date_from(),
                    runner.date_ranges[0].date_to(),
                    30,
                    database=runner.get_database(),
                )
            scheduled_hashes = [compute_query_hash(call.args[1]) for call in execute.call_args_list]
        assert len(trend_hashes) == 2
        assert trend_hashes[0] == trend_hashes[1]
        assert trend_hashes == warmer_hashes
        assert scheduled_hashes == trend_hashes[:1]
