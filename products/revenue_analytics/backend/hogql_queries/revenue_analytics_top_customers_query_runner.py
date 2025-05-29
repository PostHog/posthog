from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsTopCustomersQueryResponse,
    RevenueAnalyticsTopCustomersQueryResponse,
    RevenueAnalyticsTopCustomersQuery,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsTopCustomersQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsTopCustomersQuery
    response: RevenueAnalyticsTopCustomersQueryResponse
    cached_response: CachedRevenueAnalyticsTopCustomersQueryResponse

    def to_query(self) -> ast.SelectQuery:
        _, customer_subquery = self.revenue_subqueries()
        if customer_subquery is None:
            return ast.SelectQuery.empty()

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="name", expr=ast.Field(chain=["customers", "name"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["inner", "customer_id"])),
                ast.Alias(alias="amount", expr=ast.Field(chain=["inner", "amount"])),
                ast.Alias(alias="month", expr=ast.Field(chain=["inner", "month"])),
            ],
            select_from=ast.JoinExpr(
                table=self.inner_query(),
                alias="inner",
                next_join=ast.JoinExpr(
                    table=customer_subquery,
                    alias="customers",
                    join_type="INNER JOIN",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["customers", "id"]),
                            right=ast.Field(chain=["inner", "customer_id"]),
                            op=ast.CompareOperationOp.Eq,
                        ),
                    ),
                ),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC")],
        )

    def inner_query(self) -> ast.SelectQuery:
        charge_subquery, _ = self.revenue_subqueries()
        if charge_subquery is None:
            # Empty query because there are no charges, but still include the right columns
            # to make sure the outer query works
            return ast.SelectQuery(
                select=[
                    ast.Alias(alias="customer_id", expr=ast.Constant(value="")),
                    ast.Alias(alias="month", expr=ast.Constant(value="")),
                    ast.Alias(alias="amount", expr=ast.Constant(value=0)),
                ],
                where=ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=0),
                    op=ast.CompareOperationOp.Eq,
                ),
            )

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                ast.Alias(
                    alias="month",
                    expr=ast.Call(
                        name="toStartOfMonth",
                        args=[ast.Field(chain=["timestamp"])],
                    ),
                ),
                ast.Alias(
                    alias="amount",
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=["amount"])],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=charge_subquery),
            group_by=[ast.Field(chain=["customer_id"]), ast.Field(chain=["month"])],
        )

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_top_customers_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        return RevenueAnalyticsTopCustomersQueryResponse(
            results=response.results,
            columns=["name", "customer_id", "amount", "month"],
            modifiers=self.modifiers,
        )
