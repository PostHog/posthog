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
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog.hogql import ast

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team, User

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.backend.hogql_queries.adapters.base import MarketingSourceAdapter
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig
from products.marketing_analytics.backend.hogql_queries.marketing_cost_trends_query_runner import (
    MarketingCostTrendsQueryRunner,
)
from products.product_analytics.backend.facade.queries import TrendsQueryRunner

MODULE = "products.marketing_analytics.backend.hogql_queries.marketing_cost_trends_query_runner"


@time_machine.travel("2025-01-15T12:00:00Z", tick=False)
class TestMarketingCostTrendsQueryRunner(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team(id=17, timezone="America/New_York", base_currency="USD")
        self.user = User(id=3)
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
        self.database = self.enterContext(patch(f"{MODULE}.Database.create_for"))
        self.ensure = self.enterContext(patch(f"{MODULE}.ensure_precomputed"))
        self.config = self.enterContext(patch(f"{MODULE}.MarketingAnalyticsConfig.from_team"))
        self.config.return_value = MarketingAnalyticsConfig(costs_precomputation_enabled=True)
        self.enterContext(
            patch(
                "posthog.hogql_queries.query_runner.create_default_modifiers_for_team",
                return_value=HogQLQueryModifiers(),
            )
        )
        self.enterContext(patch(f"{MODULE}.create_default_modifiers_for_team", return_value=HogQLQueryModifiers()))

    def runner(self) -> MarketingCostTrendsQueryRunner:
        runner = get_query_runner(self.query.model_dump(mode="json"), team=self.team, user=self.user)
        assert isinstance(runner, MarketingCostTrendsQueryRunner)
        return runner

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
                (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
                (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
                (runner.query_previous_date_range.date_from(), runner.query_previous_date_range.date_to()),
                (runner.query_previous_date_range.date_from(), runner.query_previous_date_range.date_to()),
            ]
            assert runner.query_date_range.date_from() == datetime(2025, 1, 10, 5, tzinfo=UTC)
            if _name == "custom_comparison":
                assert runner.query_previous_date_range.date_from().year == 2024
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
        if case != "inaccessible_source":
            assert self.database.call_args.kwargs["user"] is self.user
            assert self.database.call_args.kwargs["bypass_warehouse_access_control"] is False

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

    @parameterized.expand([(True,), (False,)])
    def test_calculate_executes_the_resolved_series(self, ready: bool) -> None:
        self.ensure.return_value = LazyComputationResult(ready=ready, job_ids=[])

        def calculate_trend(runner: TrendsQueryRunner) -> TrendsQueryResponse:
            return TrendsQueryResponse(
                results=[
                    {"label": series.table_name}
                    for series in runner.query.series
                    if isinstance(series, DataWarehouseNode)
                ]
            )

        with patch.object(TrendsQueryRunner, "_calculate", calculate_trend):
            response = self.runner().calculate()
        expected = ["marketing_costs_precomputed"] if ready else ["source_a_stats", "source_b_stats"]
        assert [result["label"] for result in response.results] == expected
