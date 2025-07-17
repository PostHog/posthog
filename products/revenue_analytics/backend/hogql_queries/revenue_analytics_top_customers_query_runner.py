from typing import cast

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsTopCustomersQueryResponse,
    RevenueAnalyticsTopCustomersQueryResponse,
    RevenueAnalyticsTopCustomersQuery,
    ResolvedDateRangeResponse,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from products.revenue_analytics.backend.views.revenue_analytics_customer_view import RevenueAnalyticsCustomerView
from products.revenue_analytics.backend.views.revenue_analytics_invoice_item_view import RevenueAnalyticsInvoiceItemView


class RevenueAnalyticsTopCustomersQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsTopCustomersQuery
    response: RevenueAnalyticsTopCustomersQueryResponse
    cached_response: CachedRevenueAnalyticsTopCustomersQueryResponse

    def to_query(self) -> ast.SelectQuery:
        is_monthly_grouping = self.query.groupBy == "month"

        with self.timings.measure("inner_query"):
            inner_query = self.inner_query()

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="name", expr=ast.Field(chain=["inner", "name"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["inner", "customer_id"])),
                # If grouping all months together, we'll use the sum of the amount
                # Otherwise, we'll use the amount for the specific month
                ast.Alias(
                    alias="amount",
                    expr=ast.Field(chain=["inner", "amount"])
                    if is_monthly_grouping
                    else ast.Call(name="sum", args=[ast.Field(chain=["inner", "amount"])]),
                ),
                ast.Alias(
                    alias="month",
                    expr=ast.Field(chain=["inner", "month"]) if is_monthly_grouping else ast.Constant(value="all"),
                ),
            ],
            select_from=ast.JoinExpr(table=inner_query, alias="inner"),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC")],
            # Only need to group if we're grouping all months together
            group_by=[
                ast.Field(chain=["name"]),
                ast.Field(chain=["customer_id"]),
            ]
            if not is_monthly_grouping
            else [],
            # Limit by month again to limit too many rows if we're spanning more than one month
            # but still grouping them because we're using the sum of the amount
            limit_by=ast.LimitByExpr(n=ast.Constant(value=20), exprs=[ast.Field(chain=["month"])]),
        )

    def inner_query(self) -> ast.SelectQuery:
        # Empty query because there are no invoice items, but still include the right columns
        # to make sure the outer query works
        if self.revenue_subqueries.invoice_item is None:
            return ast.SelectQuery.empty(columns=["name", "customer_id", "month", "amount"])

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="name", expr=ast.Constant(value=None)),
                ast.Alias(
                    alias="customer_id",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "customer_id"]),
                ),
                ast.Alias(
                    alias="month",
                    expr=ast.Call(
                        name="toStartOfMonth",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
                ast.Alias(
                    alias="amount",
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"])],
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
                        [
                            RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                            "timestamp",
                        ]
                    ),
                    *self.where_property_exprs,
                ]
            ),
            group_by=[ast.Field(chain=["customer_id"]), ast.Field(chain=["name"]), ast.Field(chain=["month"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC")],
            # Top 20 by month only to avoid too many rows
            limit_by=ast.LimitByExpr(n=ast.Constant(value=20), exprs=[ast.Field(chain=["month"])]),
        )

        # If there's a way to join with the customer table, then do it
        if self.revenue_subqueries.customer is not None:
            join = self._create_customer_join(RevenueAnalyticsInvoiceItemView, self.revenue_subqueries.customer)
            if join is not None:
                query.select[0] = ast.Alias(
                    alias="name", expr=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "name"])
                )
                self._append_joins(cast(ast.JoinExpr, query.select_from), [join])

        return query

    def calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_top_customers_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        return RevenueAnalyticsTopCustomersQueryResponse(
            results=response.results,
            columns=response.columns,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
