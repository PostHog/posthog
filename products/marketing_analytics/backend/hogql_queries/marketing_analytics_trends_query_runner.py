from datetime import datetime
from functools import cached_property

import structlog

from posthog.schema import (
    CachedMarketingAnalyticsTrendsQueryResponse,
    HogQLQueryResponse,
    MarketingAnalyticsTrendsMetric,
    MarketingAnalyticsTrendsQuery,
    MarketingAnalyticsTrendsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.models import UnknownDatabaseField
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from .adapters.base import MarketingSourceAdapter
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner

logger = structlog.get_logger(__name__)

BREAKDOWN_ALIAS = "breakdown_by"
PERIOD_START_ALIAS = "period_start"
AMOUNT_ALIAS = "amount"


class MarketingAnalyticsTrendsQueryRunner(MarketingAnalyticsBaseQueryRunner[MarketingAnalyticsTrendsQueryResponse]):
    """Time series of a single cost metric, de-duplicated per (source, campaign, day) via the SAME
    argMax(computed_at) + job_id read the aggregated tile uses, then bucketed by interval and broken down
    by source_name. A raw TrendsQuery over marketing_costs_preaggregated sums every surviving job
    generation of a cost cell and double-counts; reusing the tile's deduped read means the chart total
    reconciles with the overview tile.
    """

    query: MarketingAnalyticsTrendsQuery
    cached_response: CachedMarketingAnalyticsTrendsQueryResponse

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        # The base runner pins interval=None (it never buckets); the chart needs the requested interval.
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=datetime.now(),
        )

    def _metric_amount_expr(self) -> ast.Expr:
        """SUM (or ratio of sums) of the selected metric over the deduped per-cell cost rows. Costs are
        already in the team's base currency at materialization time, so no convertCurrency() is needed."""
        adapter = MarketingSourceAdapter

        def total(field_name: str) -> ast.Expr:
            return ast.Call(name="sum", args=[ast.Field(chain=[field_name])])

        def ratio(numerator: str, denominator: str) -> ast.Expr:
            return ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Div,
                left=total(numerator),
                right=ast.Call(name="nullIf", args=[total(denominator), ast.Constant(value=0)]),
            )

        metric = self.query.metric
        metric_exprs: dict[MarketingAnalyticsTrendsMetric, ast.Expr] = {
            MarketingAnalyticsTrendsMetric.COST: total(adapter.cost_field),
            MarketingAnalyticsTrendsMetric.CLICKS: total(adapter.clicks_field),
            MarketingAnalyticsTrendsMetric.IMPRESSIONS: total(adapter.impressions_field),
            MarketingAnalyticsTrendsMetric.REPORTED_CONVERSION: total(adapter.reported_conversion_field),
            MarketingAnalyticsTrendsMetric.REPORTED_CONVERSION_VALUE: total(adapter.reported_conversion_value_field),
            MarketingAnalyticsTrendsMetric.ROAS: ratio(adapter.reported_conversion_value_field, adapter.cost_field),
            MarketingAnalyticsTrendsMetric.COST_PER_REPORTED_CONVERSION: ratio(
                adapter.cost_field, adapter.reported_conversion_field
            ),
        }
        try:
            return metric_exprs[metric]
        except KeyError:
            raise ValueError(f"Unsupported marketing trends metric: {metric}")

    def _empty_query(self) -> ast.SelectQuery:
        columns = [BREAKDOWN_ALIAS, PERIOD_START_ALIAS, AMOUNT_ALIAS]
        return ast.SelectQuery.empty(columns={key: UnknownDatabaseField(name=key) for key in columns})

    def to_query(self) -> ast.SelectQuery:
        date_range = self.query_date_range
        resolved = self._resolve_precompute_cost_jobs(date_range)
        if resolved is None:
            # Nothing materialized yet (sources still syncing / unmaterializable) — well-typed empty series.
            return self._empty_query()
        grain, job_ids, s3_fallback_adapters, _ = resolved
        if s3_fallback_adapters:
            # The chart reads only the deduped native table; sources that can't materialize (and would
            # otherwise fall back to the live S3 union) are omitted here. They still appear in the overview
            # tile, so this is a known, logged gap rather than a silent one.
            logger.warning(
                "marketing_costs_trends_excludes_s3_fallback",
                team_id=self.team.pk,
                grain=str(grain.value),
                excluded_sources=[a.get_source_id() for a in s3_fallback_adapters],
            )

        inner = self._costs_native_read_query(job_ids, grain, date_range, include_cost_date=True)
        # toStartOfWeek / toStartOfDay / toStartOfMonth — matches how TrendsQuery buckets, so the axis
        # produced by query_date_range.all_values() lines up with the data.
        interval_fn = f"toStartOf{self.query_date_range.interval_name.title()}"
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=BREAKDOWN_ALIAS, expr=ast.Field(chain=[MarketingSourceAdapter.source_name_field])),
                ast.Alias(
                    alias=PERIOD_START_ALIAS,
                    expr=ast.Call(
                        name=interval_fn,
                        args=[ast.Call(name="toDateTime", args=[ast.Field(chain=["cost_date"])])],
                    ),
                ),
                ast.Alias(alias=AMOUNT_ALIAS, expr=self._metric_amount_expr()),
            ],
            select_from=ast.JoinExpr(table=inner),
            group_by=[ast.Field(chain=[BREAKDOWN_ALIAS]), ast.Field(chain=[PERIOD_START_ALIAS])],
            order_by=[
                # amount first so the biggest series sorts to the front (matches revenue analytics)
                ast.OrderExpr(expr=ast.Field(chain=[AMOUNT_ALIAS]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=[BREAKDOWN_ALIAS]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=[PERIOD_START_ALIAS]), order="ASC"),
            ],
            # (# periods x # sources) rows — small, but keep a generous ceiling like revenue analytics.
            limit=ast.Constant(value=10000),
        )

    def _build_results(self, response: HogQLQueryResponse) -> list[dict]:
        """Shape rows into Insights-style GraphDataset dicts (one series per source) so the frontend can
        render them with the shared trends chart components."""
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range, self.team.week_start_day) for item in all_dates]

        def _build_result(breakdown: str, data: list) -> dict:
            return {
                "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                "data": data,
                "days": days,
                "label": breakdown,
                "labels": labels,
            }

        grouped_results: dict[tuple[str, str], float] = {}
        breakdowns: list[str] = []
        for breakdown_by, period_start, amount in response.results:
            breakdown_by = breakdown_by or ""
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)
            grouped_results[(breakdown_by, period_start.strftime("%Y-%m-%d"))] = amount

        return [
            _build_result(breakdown, [grouped_results.get((breakdown, day), 0) for day in days])
            for breakdown in breakdowns
        ]

    def _calculate(self) -> MarketingAnalyticsTrendsQueryResponse:
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="marketing_analytics_trends_query",
                query=query,
                team=self.team,
                user=self.user,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return MarketingAnalyticsTrendsQueryResponse(
            results=results,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
        )

    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        # Unused: this runner overrides to_query() and does not build the campaign_costs CTE / conversion
        # goals join. Present only to satisfy the abstract base contract.
        raise NotImplementedError("MarketingAnalyticsTrendsQueryRunner builds its query in to_query()")
