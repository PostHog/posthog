from typing import cast
from decimal import Decimal

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsGrowthRateQueryResponse,
    RevenueAnalyticsGrowthRateQueryResponse,
    RevenueAnalyticsGrowthRateQuery,
    ResolvedDateRangeResponse,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from products.revenue_analytics.backend.views.revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView

ORDER_BY_MONTH_ASC = ast.OrderExpr(expr=ast.Field(chain=["month"]), order="ASC")


class RevenueAnalyticsGrowthRateQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsGrowthRateQuery
    response: RevenueAnalyticsGrowthRateQueryResponse
    cached_response: CachedRevenueAnalyticsGrowthRateQueryResponse

    def to_query(self) -> ast.SelectQuery:
        # If there are no revenue views, we return a query that returns 0 for all values
        if self.revenue_subqueries.invoice_item is None:
            return ast.SelectQuery.empty(
                columns=[
                    "month",
                    "revenue",
                    "previous_month_revenue",
                    "month_over_month_growth_rate",
                    "three_month_growth_rate",
                    "six_month_growth_rate",
                ]
            )

        monthly_revenue_cte = self.monthly_revenue_cte()
        revenue_with_growth_cte = self.revenue_with_growth_cte(monthly_revenue_cte)

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["month"]),
                ast.Field(chain=["revenue"]),
                ast.Field(chain=["previous_month_revenue"]),
                ast.Field(chain=["month_over_month_growth_rate"]),
                ast.Alias(alias="three_month_growth_rate", expr=self.growth_rate_over_last_n_months(3)),
                ast.Alias(alias="six_month_growth_rate", expr=self.growth_rate_over_last_n_months(6)),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[revenue_with_growth_cte.name])),
            order_by=[ORDER_BY_MONTH_ASC],
            ctes={
                "monthly_revenue": monthly_revenue_cte,
                "revenue_with_growth": revenue_with_growth_cte,
            },
        )

    def monthly_revenue_cte(self) -> ast.CTE:
        return ast.CTE(
            name="monthly_revenue",
            expr=ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="month",
                        expr=ast.Call(
                            name="toStartOfMonth",
                            args=[
                                ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])
                            ],
                        ),
                    ),
                    ast.Alias(
                        alias="revenue",
                        expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])]),
                    ),
                ],
                select_from=self._append_joins(
                    ast.JoinExpr(
                        alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                        table=self.revenue_subqueries.invoice_item,  # Guaranteed to be not None because we check for that in `to_query`
                    ),
                    self.joins_for_properties(RevenueAnalyticsInvoiceItemView),
                ),
                where=ast.And(
                    exprs=[
                        self.timestamp_where_clause(
                            [RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                        ),
                        *self.where_property_exprs,
                    ]
                ),
                group_by=[ast.Field(chain=["month"])],
                order_by=[ORDER_BY_MONTH_ASC],
            ),
            cte_type="subquery",
        )

    def revenue_with_growth_cte(self, monthly_revenue_cte: ast.CTE) -> ast.CTE:
        return ast.CTE(
            name="revenue_with_growth",
            expr=ast.SelectQuery(
                select=[
                    ast.Field(chain=["month"]),
                    ast.Field(chain=["revenue"]),
                    ast.Alias(
                        alias="previous_month_revenue",
                        expr=ast.WindowFunction(
                            name="lagInFrame",
                            exprs=[ast.Field(chain=["revenue"]), ast.Constant(value=1)],
                            over_expr=ast.WindowExpr(order_by=[ORDER_BY_MONTH_ASC]),
                        ),
                    ),
                    # Month over month growth rate
                    ast.Alias(
                        alias="month_over_month_growth_rate",
                        expr=ast.Call(
                            name="divide",
                            args=[
                                ast.Call(
                                    name="minus",
                                    args=[ast.Field(chain=["revenue"]), ast.Field(chain=["previous_month_revenue"])],
                                ),
                                ast.Field(chain=["previous_month_revenue"]),
                            ],
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=[monthly_revenue_cte.name])),
            ),
            cte_type="subquery",
        )

    def growth_rate_over_last_n_months(self, n: int) -> ast.WindowFunction:
        return ast.WindowFunction(
            name="avg",
            exprs=[ast.Field(chain=["month_over_month_growth_rate"])],
            over_expr=ast.WindowExpr(
                order_by=[ORDER_BY_MONTH_ASC],
                frame_method="ROWS",
                frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=n - 1),
                frame_end=ast.WindowFrameExpr(frame_type="CURRENT ROW"),
            ),
        )

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_growth_rate_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        results = [
            (
                result[0],  # month
                result[1],  # revenue
                result[2],  # previous_month_revenue
                result[3],  # month_over_month_growth_rate
                # Need to cast to Decimal because the `avg` window function always return a Float64
                # rather than keeping the underlying Decimal type
                # https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/avg
                Decimal(str(round(result[4], 10))) if result[4] is not None else None,  # three_month_growth_rate
                Decimal(str(round(result[5], 10))) if result[5] is not None else None,  # six_month_growth_rate
            )
            for result in cast(list[tuple], response.results)
        ]

        return RevenueAnalyticsGrowthRateQueryResponse(
            results=results,
            columns=[
                "month",
                "revenue",
                "previous_month_revenue",
                "month_over_month_growth_rate",
                "three_month_growth_rate",
                "six_month_growth_rate",
            ],
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
