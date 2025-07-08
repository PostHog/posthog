from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    RevenueAnalyticsOverviewItem,
    RevenueAnalyticsOverviewItemKey,
    CachedRevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsOverviewQuery,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from posthog.hogql.database.schema.exchange_rate import EXCHANGE_RATE_DECIMAL_PRECISION
from products.revenue_analytics.backend.views.revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView


CONSTANT_ZERO = ast.Constant(value=0)


class RevenueAnalyticsOverviewQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsOverviewQuery
    response: RevenueAnalyticsOverviewQueryResponse
    cached_response: CachedRevenueAnalyticsOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery:
        # If there are no invoice item revenue views, we return a query that returns 0 for all values
        if self.revenue_subqueries.invoice_item is None:
            return ast.SelectQuery(
                select=[
                    ast.Alias(alias="revenue", expr=CONSTANT_ZERO),
                    ast.Alias(alias="paying_customer_count", expr=CONSTANT_ZERO),
                    ast.Alias(alias="avg_revenue_per_customer", expr=CONSTANT_ZERO),
                ],
            )

        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="revenue",
                    expr=ast.Call(
                        name="toDecimal",
                        args=[
                            ast.Call(name="sum", args=[ast.Field(chain=["amount"])]),
                            ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="paying_customer_count",
                    expr=ast.Call(
                        name="count",
                        distinct=True,
                        args=[ast.Field(chain=["customer_id"])],
                    ),
                ),
                ast.Alias(
                    alias="avg_revenue_per_customer",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["paying_customer_count"]),
                                right=CONSTANT_ZERO,
                                op=ast.CompareOperationOp.Eq,
                            ),
                            CONSTANT_ZERO,
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Call(
                                        name="divideDecimal",
                                        args=[
                                            ast.Field(chain=["revenue"]),
                                            ast.Call(
                                                name="toDecimal",
                                                args=[
                                                    ast.Field(chain=["paying_customer_count"]),
                                                    ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                                                ],
                                            ),
                                        ],
                                    ),
                                    CONSTANT_ZERO,
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            select_from=self._append_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                    table=self.revenue_subqueries.invoice_item,
                ),
                self.joins_for_properties(RevenueAnalyticsInvoiceItemView),
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        [RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"],
                    ),
                    *self.where_property_exprs,
                ]
            ),
        )

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_overview_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        assert response.results

        results = map_to_results(response.results)

        return RevenueAnalyticsOverviewQueryResponse(
            results=results,
            modifiers=self.modifiers,
        )


def map_to_results(results: list[dict]) -> list[RevenueAnalyticsOverviewItem]:
    result = results[0]  # Only care about the first result
    return [
        RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.REVENUE, value=result[0] or 0),
        RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=result[1]),
        RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=result[2]),
    ]
