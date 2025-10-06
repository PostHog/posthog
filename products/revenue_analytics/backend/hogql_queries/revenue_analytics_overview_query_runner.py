from posthog.schema import (
    CachedRevenueAnalyticsOverviewQueryResponse,
    ResolvedDateRangeResponse,
    RevenueAnalyticsOverviewItem,
    RevenueAnalyticsOverviewItemKey,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsOverviewQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.query import execute_hogql_query

from products.revenue_analytics.backend.views import RevenueAnalyticsBaseView, RevenueAnalyticsRevenueItemView

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner

ZERO_DECIMAL = ast.Call(
    name="toDecimal", args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)]
)


class RevenueAnalyticsOverviewQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsOverviewQueryResponse]):
    query: RevenueAnalyticsOverviewQuery
    cached_response: CachedRevenueAnalyticsOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        subqueries = list(self.revenue_subqueries(RevenueAnalyticsRevenueItemView))

        # If there is no revenue item view, we return a query that returns 0 for all values
        if not subqueries:
            return ast.SelectQuery(
                select=[
                    ast.Alias(alias="revenue", expr=ZERO_DECIMAL),
                    ast.Alias(alias="paying_customer_count", expr=ZERO_DECIMAL),
                    ast.Alias(alias="avg_revenue_per_customer", expr=ZERO_DECIMAL),
                ],
            )

        queries = [self._to_query_from(subquery) for subquery in subqueries]

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="revenue", expr=ast.Call(name="sum", args=[ast.Field(chain=["revenue"])])),
                ast.Alias(
                    alias="paying_customer_count",
                    expr=ast.Call(name="sum", args=[ast.Field(chain=["paying_customer_count"])]),
                ),
                ast.Alias(
                    alias="avg_revenue_per_customer",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["paying_customer_count"]),
                                right=ZERO_DECIMAL,
                                op=ast.CompareOperationOp.Eq,
                            ),
                            ZERO_DECIMAL,
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
                                    ZERO_DECIMAL,
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")),
        )

    def _to_query_from(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="revenue",
                    expr=ast.Call(
                        name="coalesce",
                        args=[
                            ast.Call(
                                name="toDecimal",
                                args=[
                                    ast.Call(
                                        name="sum",
                                        args=[
                                            ast.Field(
                                                chain=[
                                                    RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                                                    "amount",
                                                ]
                                            )
                                        ],
                                    ),
                                    ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                                ],
                            ),
                            ZERO_DECIMAL,
                        ],
                    ),
                ),
                ast.Alias(
                    alias="paying_customer_count",
                    expr=ast.Call(
                        name="count",
                        distinct=True,
                        args=[
                            ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"])
                        ],
                    ),
                ),
            ],
            select_from=self._with_where_property_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                    table=ast.Field(chain=[view.name]),
                ),
                view,
            ),
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        [RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"]),
                        right=ZERO_DECIMAL,
                    ),
                    *self.where_property_exprs(view),
                ]
            ),
        )

        return query

    def _calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_overview_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        assert response.results
        assert len(response.results) == 1

        results = [
            RevenueAnalyticsOverviewItem(key=key, value=value)
            for key, value in zip(RevenueAnalyticsOverviewItemKey, response.results[0])
        ]

        return RevenueAnalyticsOverviewQueryResponse(
            results=results,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(), date_to=self.query_date_range.date_to()
            ),
        )
