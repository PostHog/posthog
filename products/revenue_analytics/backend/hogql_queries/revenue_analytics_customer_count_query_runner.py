from decimal import Decimal
from functools import cached_property

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    HogQLQueryResponse,
    CachedRevenueAnalyticsCustomerCountQueryResponse,
    RevenueAnalyticsCustomerCountQueryResponse,
    RevenueAnalyticsCustomerCountQuery,
)
from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from products.revenue_analytics.backend.views import RevenueAnalyticsInvoiceItemView, RevenueAnalyticsSubscriptionView

from .revenue_analytics_query_runner import (
    RevenueAnalyticsQueryRunner,
)

KINDS = [
    "Subscription Count",
    "New Subscription Count",
    "Churned Subscription Count",
    "Customer Count",
    "New Customer Count",
    "Churned Customer Count",
]


class RevenueAnalyticsCustomerCountQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsCustomerCountQuery
    response: RevenueAnalyticsCustomerCountQueryResponse
    cached_response: CachedRevenueAnalyticsCustomerCountQueryResponse

    def to_query(self) -> ast.SelectQuery:
        if self.revenue_subqueries.subscription is None:
            return ast.SelectQuery.empty(
                columns=[
                    "breakdown_by",
                    "period_start",
                    "subscription_count",
                    "new_subscription_count",
                    "churned_subscription_count",
                    "customer_count",
                    "new_customer_count",
                    "churned_customer_count",
                ]
            )

        with self.timings.measure("get_subquery"):
            subquery = self._get_subquery()

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["period_start"]),
                # Aggregate subscriptions across all customers
                ast.Alias(
                    alias="subscription_count",
                    expr=ast.Call(name="sum", args=[ast.Field(chain=["subquery", "subscription_count"])]),
                ),
                ast.Alias(
                    alias="new_subscription_count",
                    expr=ast.Call(name="sum", args=[ast.Field(chain=["subquery", "new_subscription_count"])]),
                ),
                ast.Alias(
                    alias="churned_subscription_count",
                    expr=ast.Call(name="sum", args=[ast.Field(chain=["subquery", "churned_subscription_count"])]),
                ),
                # For each customer, just check whether we have at least one subscription, and for new/churned we can use the grouped data
                ast.Alias(
                    alias="customer_count",
                    expr=ast.Call(
                        name="countIf",
                        args=[
                            ast.Field(chain=["subquery", "customer_id"]),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.GtEq,
                                left=ast.Field(chain=["subquery", "subscription_count"]),
                                right=ast.Constant(value=1),
                            ),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="new_customer_count",
                    expr=ast.Call(
                        name="countIf",
                        args=[
                            ast.Field(chain=["subquery", "customer_id"]),
                            ast.Field(chain=["subquery", "is_new_customer"]),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="churned_customer_count",
                    expr=ast.Call(
                        name="countIf",
                        args=[
                            ast.Field(chain=["subquery", "customer_id"]),
                            ast.Field(chain=["subquery", "is_churned_customer"]),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(alias="subquery", table=subquery),
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["period_start"]),
            ],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["subscription_count"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["customer_count"]), order="DESC"),
            ],
            # Need a huge limit because we need (dates x breakdown)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

    def _get_subquery(self) -> ast.SelectQuery:
        with self.timings.measure("subquery"):
            dates_expr = self._dates_expr()

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Field(chain=["customer_id"]),
                ast.Alias(alias="period_start", expr=dates_expr),
                ast.Alias(
                    alias="subscription_count",
                    expr=ast.Call(
                        name="countIf",
                        distinct=True,
                        args=[
                            ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                            ast.And(
                                exprs=[
                                    self._period_lteq_expr(
                                        ast.Field(chain=["started_at"]), ast.Field(chain=["period_start"])
                                    ),
                                    self._period_gteq_expr(
                                        ast.Field(chain=["ended_at"]), ast.Field(chain=["period_start"])
                                    ),
                                ]
                            ),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="prev_subscription_count",
                    # Count how many active had on the previous period by subtracting 1 "period" on the calculation
                    # Useful to know whether a customer is new or not
                    expr=ast.Call(
                        name="countIf",
                        distinct=True,
                        args=[
                            ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                            ast.And(
                                exprs=[
                                    self._period_lteq_expr(
                                        ast.Field(chain=["started_at"]),
                                        self._add_period_expr(ast.Field(chain=["period_start"]), -1),
                                    ),
                                    self._period_gteq_expr(
                                        ast.Field(chain=["ended_at"]),
                                        self._add_period_expr(ast.Field(chain=["period_start"]), -1),
                                    ),
                                ]
                            ),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="new_subscription_count",
                    expr=ast.Call(
                        name="countIf",
                        distinct=True,
                        args=[
                            ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                            self._period_eq_expr(ast.Field(chain=["started_at"]), ast.Field(chain=["period_start"])),
                        ],
                    ),
                ),
                ast.Alias(
                    alias="churned_subscription_count",
                    expr=ast.Call(
                        name="countIf",
                        distinct=True,
                        args=[
                            ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                            self._period_eq_expr(ast.Field(chain=["ended_at"]), ast.Field(chain=["period_start"])),
                        ],
                    ),
                ),
                # Simple boolean flags to check whether a customer is new/churned
                ast.Alias(
                    alias="is_new_customer",
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["prev_subscription_count"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["subscription_count"]),
                                right=ast.Constant(value=0),
                            ),
                        ]
                    ),
                ),
                ast.Alias(
                    alias="is_churned_customer",
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["churned_subscription_count"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["churned_subscription_count"]),
                                right=ast.Field(chain=["subscription_count"]),
                            ),
                        ]
                    ),
                ),
            ],
            select_from=self._append_joins(
                ast.JoinExpr(
                    alias=RevenueAnalyticsSubscriptionView.get_generic_view_alias(),
                    table=self.revenue_subqueries.subscription,
                ),
                self.joins_for_properties(RevenueAnalyticsSubscriptionView),
            ),
            group_by=[
                ast.Field(chain=["customer_id"]),
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["period_start"]),
            ],
            where=ast.And(exprs=self._parsed_where_property_exprs) if self._parsed_where_property_exprs else None,
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["customer_id"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
            ],
        )

        # Limit to 2 group bys at most for performance reasons
        # This is also implemented in the frontend, but let's guarantee it here too
        with self.timings.measure("append_group_by"):
            for group_by in self.query.groupBy[:2]:
                query = self._append_group_by(query, RevenueAnalyticsSubscriptionView, group_by)

        return query

    @cached_property
    def _parsed_where_property_exprs(self) -> list[ast.Expr]:
        where_property_exprs = self.where_property_exprs

        # We can't join from a subscription back to the invoice item table,
        # so let's remove any where property exprs that are comparing to the invoice item table
        return [
            expr
            for expr in where_property_exprs
            if isinstance(expr, ast.CompareOperation)
            and isinstance(expr.left, ast.Field)
            and expr.left.chain[0] != RevenueAnalyticsInvoiceItemView.get_generic_view_alias()
        ]

    def _dates_expr(self) -> ast.Expr:
        return ast.Call(
            name=f"toStartOf{self.query_date_range.interval_name.title()}",
            args=[
                ast.Call(
                    name="toDateTime",
                    args=[
                        ast.Call(
                            name="arrayJoin",
                            args=[ast.Constant(value=self.query_date_range.all_values())],
                        )
                    ],
                )
            ],
        )

    def _add_period_expr(self, date: ast.Expr, offset: int) -> ast.Expr:
        return ast.Call(
            name="date_add",
            args=[
                date,
                ast.Call(
                    name=f"toInterval{self.query_date_range.interval_name.title()}",
                    args=[ast.Constant(value=offset)],
                ),
            ],
        )

    def _build_results(self, response: HogQLQueryResponse) -> list[dict]:
        # We want the result to look just like the Insights query results look like to simplify our UI
        # First, let's generate all of the dates/labels because they'll be exactly the same for all of the results
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range, self.team.week_start_day) for item in all_dates]

        # We can also group the results we have by a tuple of (breakdown_by, period_start)
        # This will allow us to easily query the results by breakdown_by and period_start
        # and then we can just add the data to the results
        # [0, 1, 2] -> [value, period_start, breakdown_by]
        grouped_results: dict[tuple[str, str], Decimal] = {}
        breakdowns = []
        for breakdown_by, period_start, *counts in response.results:
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)

            for count, kind in zip(counts, KINDS):
                grouped_results[(self._format_breakdown(breakdown_by, kind), period_start.strftime("%Y-%m-%d"))] = count

        return [
            {
                "action": {
                    "days": all_dates,
                    "id": self._format_breakdown(breakdown, kind),
                    "name": self._format_breakdown(breakdown, kind),
                },
                "data": [grouped_results.get((self._format_breakdown(breakdown, kind), day), 0) for day in days],
                "days": days,
                "label": self._format_breakdown(breakdown, kind),
                "labels": labels,
            }
            for breakdown in breakdowns
            for kind in KINDS
        ]

    def _format_breakdown(self, breakdown: str, kind: str) -> str:
        return f"{kind} | {breakdown}"

    def calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_customer_count_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsCustomerCountQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
