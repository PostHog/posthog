from decimal import Decimal

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsGrowthRateQueryResponse,
    RevenueAnalyticsGrowthRateQueryResponse,
    RevenueAnalyticsGrowthRateQuery,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsGrowthRateQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsGrowthRateQuery
    response: RevenueAnalyticsGrowthRateQueryResponse
    cached_response: CachedRevenueAnalyticsGrowthRateQueryResponse

    def to_query(self) -> ast.SelectQuery:
        # If there are no revenue views, we return a query that returns 0 for all values
        charge_subquery, _ = self.revenue_subqueries()
        if charge_subquery is None:
            return ast.SelectQuery.empty()

        monthly_mrr_cte = self.monthly_mrr_cte(charge_subquery)
        mrr_with_growth_cte = self.mrr_with_growth_cte(monthly_mrr_cte)

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["month"]),
                ast.Alias(alias="mrr", expr=ast.Field(chain=["mrr_avg"])),
                ast.Alias(alias="previous_mrr", expr=ast.Field(chain=["previous_mrr_avg"])),
                ast.Alias(
                    alias="mrr_growth_rate",
                    expr=ast.Call(
                        name="divide",
                        args=[
                            ast.Call(
                                name="minus", args=[ast.Field(chain=["mrr_avg"]), ast.Field(chain=["previous_mrr_avg"])]
                            ),
                            ast.Field(chain=["previous_mrr_avg"]),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[mrr_with_growth_cte.name])),
            where=ast.Call(
                name="isNotNull",
                args=[ast.Field(chain=["previous_mrr_avg"])],
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["month"]), order="DESC")],
            ctes={
                "monthly_mrr": monthly_mrr_cte,
                "mrr_with_growth": mrr_with_growth_cte,
            },
            limit=ast.Constant(value=24),  # Limit to last 24 months
        )

    def monthly_mrr_cte(self, select_from: ast.SelectQuery | ast.SelectSetQuery) -> ast.CTE:
        return ast.CTE(
            name="monthly_mrr",
            expr=ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="month",
                        expr=ast.Call(name="toStartOfMonth", args=[ast.Field(chain=["timestamp"])]),
                    ),
                    ast.Alias(
                        alias="mrr",
                        expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])]),
                    ),
                ],
                select_from=ast.JoinExpr(table=select_from),
                group_by=[ast.Field(chain=["month"])],
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["month"]))],
            ),
            cte_type="subquery",
        )

    def mrr_with_growth_cte(self, monthly_mrr_cte: ast.CTE) -> ast.CTE:
        return ast.CTE(
            name="mrr_with_growth",
            expr=ast.SelectQuery(
                select=[
                    ast.Field(chain=["month"]),
                    ast.Field(chain=["mrr"]),
                    # Equivalent to: "avg(mrr) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS mrr_avg"
                    ast.Alias(
                        alias="mrr_avg",
                        expr=ast.WindowFunction(
                            name="avg",
                            exprs=[ast.Field(chain=["mrr"])],
                            over_expr=ast.WindowExpr(
                                order_by=[ast.OrderExpr(expr=ast.Field(chain=["month"]), order="ASC")],
                                frame_method="ROWS",
                                frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=2),
                                frame_end=ast.WindowFrameExpr(frame_type="CURRENT ROW"),
                            ),
                        ),
                    ),
                    # Equivalent to: "avg(mrr) OVER (ORDER BY month ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS previous_mrr_avg"
                    ast.Alias(
                        alias="previous_mrr_avg",
                        expr=ast.WindowFunction(
                            name="avg",
                            exprs=[ast.Field(chain=["mrr"])],
                            over_expr=ast.WindowExpr(
                                order_by=[ast.OrderExpr(expr=ast.Field(chain=["month"]), order="ASC")],
                                frame_method="ROWS",
                                frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=3),
                                frame_end=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=1),
                            ),
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=[monthly_mrr_cte.name])),
            ),
            cte_type="subquery",
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
                result[0],
                Decimal(str(round(result[1], 10))),
                Decimal(str(round(result[2], 10))),
                Decimal(str(round(result[3], 10))),
            )
            for result in response.results
        ]

        return RevenueAnalyticsGrowthRateQueryResponse(
            results=results,
            columns=["month", "mrr", "previous_mrr", "mrr_growth_rate"],
            modifiers=self.modifiers,
        )
