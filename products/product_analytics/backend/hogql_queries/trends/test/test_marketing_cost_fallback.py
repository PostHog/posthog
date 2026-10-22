from collections.abc import Callable, Sequence
from datetime import UTC, datetime

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    DataWarehouseNode,
    DateRange,
    HogQLQueryModifiers,
    MarketingAnalyticsCostFallback,
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog.hogql.database.database import Database

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team, User

from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner


@time_machine.travel("2025-01-15T12:00:00Z", tick=False)
class TestMarketingCostFallback(SimpleTestCase):
    @parameterized.expand([(True, None), (False, None), (True, "-1y"), (False, "-1y")])
    def test_resolved_series_reuse_database_and_exact_trends_periods(self, ready: bool, compare_to: str | None) -> None:
        team = Team(id=17, timezone="America/New_York", base_currency="USD")
        user = User(id=3)
        precomputed = DataWarehouseNode(
            id="marketing_costs_precomputed",
            table_name="marketing_costs_precomputed",
            id_field="campaign_id",
            distinct_id_field="campaign_id",
            timestamp_field="timestamp",
        )
        live = DataWarehouseNode(
            id="source_stats", table_name="source_stats", id_field="id", distinct_id_field="id", timestamp_field="date"
        )
        query = TrendsQuery(
            interval="day",
            dateRange=DateRange(date_from="2025-01-10", date_to="2025-01-12"),
            compareFilter=CompareFilter(compare=True, compare_to=compare_to),
            series=[precomputed],
            marketingAnalyticsCostFallback=MarketingAnalyticsCostFallback(series=[live], sourceIds=["a"]),
        )
        original_calculate = TrendsQueryRunner.calculate

        def execute_resolved(runner: TrendsQueryRunner) -> TrendsQueryResponse:
            if runner.query.marketingAnalyticsCostFallback is not None:
                return original_calculate(runner)
            assert runner.shared_database is database.return_value
            series = runner.query.series[0]
            assert isinstance(series, DataWarehouseNode)
            return TrendsQueryResponse(results=[{"label": series.table_name}])

        def resolve(
            *,
            query: TrendsQuery,
            team: Team,
            date_ranges: Sequence[QueryDateRange],
            get_database: Callable[[], Database],
        ) -> TrendsQuery:
            assert len(date_ranges) == 2
            assert date_ranges[0].date_from() == datetime(2025, 1, 10, 5, tzinfo=UTC)
            assert date_ranges[1].date_from().year == (2024 if compare_to else 2025)
            assert get_database() is database.return_value
            result = query.model_copy(deep=True)
            result.marketingAnalyticsCostFallback = None
            result.series = [precomputed if ready else live]
            return result

        with (
            patch("posthog.hogql_queries.query_runner.Database.create_for") as database,
            patch(
                "posthog.hogql_queries.query_runner.create_default_modifiers_for_team",
                return_value=HogQLQueryModifiers(),
            ),
            patch("posthog.hogql_queries.query_runner.get_instance_setting", return_value=True),
            patch(
                "products.marketing_analytics.backend.facade.queries.resolve_marketing_cost_trend", side_effect=resolve
            ),
            patch.object(TrendsQueryRunner, "calculate", execute_resolved),
        ):
            result = TrendsQueryRunner(query=query, team=team, user=user).calculate()
        assert result.results[0]["label"] == ("marketing_costs_precomputed" if ready else "source_stats")
        database.assert_called_once()
        assert database.call_args.kwargs["user"] is user
        assert not database.call_args.kwargs.get("bypass_warehouse_access_control", False)
