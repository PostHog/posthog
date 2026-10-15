from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.schema import (
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    MarketingAnalyticsDrillDownLevel,
    PropertyOperator,
)

from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.models.team.team import DEFAULT_CURRENCY

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.product_analytics.backend.facade.queries import TrendsQueryRunner

from .adapters.base import QueryContext
from .adapters.factory import MarketingSourceFactory
from .marketing_analytics_base_query_runner import costs_precompute_ttl_schedule
from .marketing_analytics_config import MarketingAnalyticsConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

    from posthog.schema import TrendsQuery, TrendsQueryResponse

    from posthog.hogql_queries.utils.query_date_range import QueryDateRange

logger = structlog.get_logger(__name__)


class MarketingCostTrendsQueryRunner(TrendsQueryRunner):
    def _covered_source_ids(self, date_ranges: Sequence[QueryDateRange]) -> list[str] | None:
        fallback = self.query.marketingAnalyticsCostFallback
        assert fallback is not None
        selected_ids = set(fallback.sourceIds)
        if not selected_ids or not date_ranges:
            return None
        database = Database.create_for(
            team=self.team,
            user=self.user,
            modifiers=create_default_modifiers_for_team(self.team, self.modifiers),
            timings=self.timings,
            build_postgres_foreign_keys=False,
            bypass_warehouse_access_control=False,
        )
        for date_range in date_ranges:
            factory = MarketingSourceFactory(
                context=QueryContext(
                    date_range=date_range,
                    team=self.team,
                    base_currency=self.team.base_currency or DEFAULT_CURRENCY,
                    drill_down_level=MarketingAnalyticsDrillDownLevel.CAMPAIGN,
                    database=database,
                )
            )
            adapters = factory.get_valid_adapters(factory.create_adapters())
            adapters = [adapter for adapter in adapters if adapter.get_source_id() in selected_ids]
            source_ids = {str(adapter.get_source_id()) for adapter in adapters}
            if not source_ids or source_ids != selected_ids:
                return None
            for adapter in adapters:
                if not adapter.supports_level(MarketingAnalyticsDrillDownLevel.CAMPAIGN):
                    return None
                insert_query = adapter.build_materialization_query(adapter.get_source_id())
                if insert_query is None:
                    return None
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
            date_ranges = [self.query_date_range]
            if self.query.compareFilter and self.query.compareFilter.compare:
                date_ranges.append(self.query_previous_date_range)
            source_ids = self._covered_source_ids(date_ranges)
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

    def _calculate(self) -> TrendsQueryResponse:
        return TrendsQueryRunner(
            query=self.resolve_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            user=self.user,
            workload=self.workload,
            hogql_settings=self.hogql_settings,
        ).calculate()
