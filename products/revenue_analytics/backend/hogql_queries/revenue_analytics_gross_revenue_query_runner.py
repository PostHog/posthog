from decimal import Decimal

from posthog.schema import (
    CachedRevenueAnalyticsGrossRevenueQueryResponse,
    HogQLQueryResponse,
    ResolvedDateRangeResponse,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsGrossRevenueQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from products.revenue_analytics.backend.views import RevenueAnalyticsRevenueItemView

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsGrossRevenueQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsGrossRevenueQueryResponse]):
    query: RevenueAnalyticsGrossRevenueQuery
    cached_response: CachedRevenueAnalyticsGrossRevenueQueryResponse

    def to_query(self) -> ast.SelectQuery:
        revenue_item_subquery = self.revenue_subqueries.revenue_item
        if revenue_item_subquery is None:
            return ast.SelectQuery.empty(columns=["breakdown_by", "period_start", "amount"])

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(
                    alias="period_start",
                    expr=ast.Call(
                        name=f"toStartOf{self.query_date_range.interval_name.title()}",
                        args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
                ast.Alias(alias="amount", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
            ],
            select_from=self._append_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                    table=revenue_item_subquery,
                ),
                self.joins_for_properties(RevenueAnalyticsRevenueItemView),
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    *self.where_property_exprs,
                ]
            ),
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["period_start"]),
            ],
            order_by=[
                # `amount` first to have bigger numbers first
                ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
            ],
            # Need a huge limit because we need (# periods x # breakdowns)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

        # Limit to 2 group bys at most for performance reasons
        # This is also implemented in the frontend, but let's guarantee it here as well
        with self.timings.measure("append_group_by"):
            for group_by in self.query.groupBy[:2]:
                query = self._append_group_by(query, RevenueAnalyticsRevenueItemView, group_by)

        return query

    def _build_results(self, response: HogQLQueryResponse) -> list[dict]:
        # We want the result to look just like the Insights query results look like to simplify our UI
        # First, let's generate all of the dates/labels because they'll be exactly the same for all of the results
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range, self.team.week_start_day) for item in all_dates]

        def _build_result(breakdown: str, data: list[Decimal]) -> dict:
            return {
                "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                "data": data,
                "days": days,
                "label": breakdown,
                "labels": labels,
            }

        # We can also group the results we have by a tuple of (breakdown_by, period_start)
        # This will allow us to easily query the results by breakdown_by and period_start
        # and then we can just add the data to the results
        grouped_results: dict[tuple[str, str], Decimal] = {}
        breakdowns: list[str] = []
        for breakdown_by, period_start, amount in response.results:
            # Use array to guarantee insertion order
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)
            grouped_results[(breakdown_by, period_start.strftime("%Y-%m-%d"))] = amount

        return [
            _build_result(breakdown, [grouped_results.get((breakdown, day), Decimal(0)) for day in days])
            for breakdown in breakdowns
        ]

    def _calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_gross_revenue_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsGrossRevenueQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
