from posthog.schema import (
    CachedRevenueAnalyticsTopCustomersQueryResponse,
    ResolvedDateRangeResponse,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.database.models import UnknownDatabaseField
from posthog.hogql.query import execute_hogql_query

from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsRevenueItemView,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsTopCustomersQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsTopCustomersQueryResponse]):
    query: RevenueAnalyticsTopCustomersQuery
    cached_response: CachedRevenueAnalyticsTopCustomersQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        subqueries = list(self.revenue_subqueries(RevenueAnalyticsRevenueItemView))
        if not subqueries:
            columns = ["customer_id", "name", "amount", "month"]
            return ast.SelectQuery.empty(columns={key: UnknownDatabaseField(name=key) for key in columns})

        queries = [self._to_query_from(subquery) for subquery in subqueries]
        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")

    def _to_query_from(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        is_monthly_grouping = self.query.groupBy == "month"

        with self.timings.measure("inner_query"):
            inner_query = self.inner_query(view)

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["inner", "customer_id"])),
                ast.Alias(alias="name", expr=ast.Field(chain=["customer_id"])),
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
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["name"]),
            ]
            if not is_monthly_grouping
            else [],
            # Limit by month again to limit too many rows if we're spanning more than one month
            # but still grouping them because we're using the sum of the amount
            limit_by=ast.LimitByExpr(n=ast.Constant(value=20), exprs=[ast.Field(chain=["month"])]),
        )

        customer_views = self.revenue_subqueries(RevenueAnalyticsCustomerView)
        customer_view = next(
            (customer_view for customer_view in customer_views if customer_view.prefix == view.prefix), None
        )
        if customer_view is not None and query.select_from is not None:
            query.select_from.next_join = ast.JoinExpr(
                alias=RevenueAnalyticsCustomerView.get_generic_view_alias(),
                table=ast.Field(chain=[customer_view.name]),
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["inner", "customer_id"]),
                        right=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "id"]),
                    ),
                ),
            )

            if len(query.select) >= 2 and isinstance(query.select[1], ast.Alias) and query.select[1].alias == "name":
                query.select[1] = ast.Alias(
                    alias="name", expr=ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "name"])
                )
            else:
                raise ValueError("Name field not found in second position of query select")

        return query

    def inner_query(self, view: RevenueAnalyticsBaseView) -> ast.SelectQuery:
        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="customer_id",
                    expr=ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "customer_id"]),
                ),
                ast.Alias(
                    alias="month",
                    expr=ast.Call(
                        name="toStartOfMonth",
                        args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
                ast.Alias(
                    alias="amount",
                    expr=ast.Call(
                        name="sum",
                        args=[ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"])],
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
                        [
                            RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                            "timestamp",
                        ]
                    ),
                    *self.where_property_exprs(view),
                ]
            ),
            group_by=[ast.Field(chain=["customer_id"]), ast.Field(chain=["month"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["amount"]), order="DESC")],
            # Top 20 by month only to avoid too many rows
            limit_by=ast.LimitByExpr(n=ast.Constant(value=20), exprs=[ast.Field(chain=["month"])]),
        )

        return query

    def _calculate(self):
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
