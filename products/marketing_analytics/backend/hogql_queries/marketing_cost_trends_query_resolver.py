from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.schema import (
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    MarketingAnalyticsDrillDownLevel,
    PropertyOperator,
)

from posthog.models.team.team import DEFAULT_CURRENCY

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)

from .adapters.base import QueryContext
from .adapters.factory import MarketingSourceFactory
from .marketing_analytics_base_query_runner import costs_precompute_ttl_schedule
from .marketing_analytics_config import MarketingAnalyticsConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from posthog.schema import TrendsQuery

    from posthog.hogql.database.database import Database

    from posthog.hogql_queries.utils.query_date_range import QueryDateRange
    from posthog.models import Team

logger = structlog.get_logger(__name__)


class MarketingCostTrendsQueryResolver:
    def __init__(
        self,
        query: TrendsQuery,
        team: Team,
        date_ranges: Sequence[QueryDateRange],
        get_database: Callable[[], Database],
    ) -> None:
        self.query = query
        self.team = team
        self.date_ranges = date_ranges
        self.get_database = get_database

    def _covered_source_ids(self, date_ranges: Sequence[QueryDateRange]) -> list[str] | None:
        fallback = self.query.marketingAnalyticsCostFallback
        assert fallback is not None
        selected_ids = set(fallback.sourceIds)
        if not selected_ids or not date_ranges:
            return None
        grain = MarketingAnalyticsDrillDownLevel.CAMPAIGN
        factory = MarketingSourceFactory(
            context=QueryContext(
                date_range=date_ranges[0],
                team=self.team,
                base_currency=self.team.base_currency or DEFAULT_CURRENCY,
                drill_down_level=grain,
                database=self.get_database(),
            )
        )
        adapters = factory.get_valid_adapters(factory.create_adapters())
        adapters = [adapter for adapter in adapters if adapter.get_source_id() in selected_ids]
        queries = factory.build_materialization_queries(adapters, grain)
        if set(queries) != selected_ids or any(query is None for query in queries.values()):
            return None
        for date_range in date_ranges:
            for insert_query in queries.values():
                assert insert_query is not None
                # The chart excludes expired rows, so the marketing wrapper's stale grace cannot apply.
                result = ensure_precomputed(
                    team=self.team,
                    insert_query=insert_query,
                    time_range_start=date_range.date_from(),
                    time_range_end=date_range.date_to(),
                    ttl_seconds=costs_precompute_ttl_schedule(self.team),
                    table=LazyComputationTable.MARKETING_COSTS_PREAGGREGATED,
                    run_inserts=False,
                    stale_while_revalidate_seconds=0,
                )
                if not result.ready or result.stale or result.freshly_built:
                    return None
        return sorted(selected_ids)

    def resolve_query(self) -> TrendsQuery:
        fallback = self.query.marketingAnalyticsCostFallback
        assert fallback is not None
        requested_query = self.query.model_copy(deep=True)
        requested_query.marketingAnalyticsCostFallback = None
        if (
            len(self.query.series) != 1
            or not isinstance(self.query.series[0], DataWarehouseNode)
            or self.query.series[0].table_name != "marketing_costs_precomputed"
        ):
            return requested_query
        live_query = requested_query.model_copy(deep=True)
        live_query.series = [series.model_copy(deep=True) for series in fallback.series]
        live_query.breakdownFilter = None
        if not fallback.series or (self.query.dateRange and self.query.dateRange.date_from == "all"):
            return live_query
        try:
            if not MarketingAnalyticsConfig.from_team(self.team).costs_precomputation_enabled:
                return live_query
            source_ids = self._covered_source_ids(self.date_ranges)
            if source_ids is None:
                return live_query
        except Exception:
            logger.exception("marketing_cost_trend_coverage_check_failed", team_id=self.team.pk)
            return live_query

        precomputed_query = self.query.model_copy(deep=True)
        precomputed_query.marketingAnalyticsCostFallback = None
        series = precomputed_query.series[0]
        assert isinstance(series, DataWarehouseNode)
        # Scope the shared precompute table to sources visible to this caller, even without an explicit selection.
        series.properties = [prop for prop in (series.properties or []) if getattr(prop, "key", None) != "source_id"]
        series.properties.append(
            DataWarehousePropertyFilter(key="source_id", operator=PropertyOperator.EXACT, value=list(source_ids))
        )
        return precomputed_query


def resolve_marketing_cost_trend(
    *,
    query: TrendsQuery,
    team: Team,
    date_ranges: Sequence[QueryDateRange],
    get_database: Callable[[], Database],
) -> TrendsQuery:
    return MarketingCostTrendsQueryResolver(query, team, date_ranges, get_database).resolve_query()
