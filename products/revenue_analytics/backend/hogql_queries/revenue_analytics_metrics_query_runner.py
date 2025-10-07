from decimal import Decimal
from typing import Optional

from posthog.schema import (
    CachedRevenueAnalyticsMetricsQueryResponse,
    HogQLQueryResponse,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMetricsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION

from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsRevenueItemView,
    RevenueAnalyticsSubscriptionView,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner

KINDS = [
    "Subscription Count",
    "New Subscription Count",
    "Churned Subscription Count",
    "Customer Count",
    "New Customer Count",
    "Churned Customer Count",
    "ARPU",
    "LTV",
]


class RevenueAnalyticsMetricsQueryRunner(RevenueAnalyticsQueryRunner[RevenueAnalyticsMetricsQueryResponse]):
    query: RevenueAnalyticsMetricsQuery
    cached_response: CachedRevenueAnalyticsMetricsQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        subscription_subqueries = list(self.revenue_subqueries(RevenueAnalyticsSubscriptionView))
        revenue_item_subqueries = list(self.revenue_subqueries(RevenueAnalyticsRevenueItemView))
        if not subscription_subqueries:
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
                    "arpu",
                    "ltv",
                ]
            )

        queries: list[ast.SelectQuery] = []
        for subscription_subquery in subscription_subqueries:
            revenue_item_subquery = next(
                (
                    revenue_item_subquery
                    for revenue_item_subquery in revenue_item_subqueries
                    if revenue_item_subquery.prefix == subscription_subquery.prefix
                ),
                None,
            )
            queries.append(self._to_query_from(subscription_subquery, revenue_item_subquery))

        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")

    def _to_query_from(
        self,
        subscription_view: RevenueAnalyticsBaseView,
        revenue_item_view: Optional[RevenueAnalyticsBaseView],
    ) -> ast.SelectQuery:
        with self.timings.measure("get_subquery"):
            subquery = self._get_subquery(subscription_view, revenue_item_view)

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
                # ARPU calculation (revenue / customer_count)
                ast.Alias(
                    alias="arpu",
                    expr=ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(
                                name="toDecimal",
                                args=[
                                    ast.Call(
                                        name="if",
                                        args=[
                                            ast.Or(
                                                exprs=[
                                                    ast.Call(name="isNull", args=[ast.Field(chain=["customer_count"])]),
                                                    ast.CompareOperation(
                                                        op=ast.CompareOperationOp.Eq,
                                                        left=ast.Field(chain=["customer_count"]),
                                                        right=ast.Constant(value=0),
                                                    ),
                                                ],
                                            ),
                                            ast.Constant(value=0),
                                            ast.Call(
                                                name="divide",
                                                args=[
                                                    ast.Call(name="sum", args=[ast.Field(chain=["revenue"])]),
                                                    ast.Field(chain=["customer_count"]),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                                ],
                            ),
                            ast.Call(
                                name="toDecimal",
                                args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                            ),
                        ],
                    ),
                ),
                # LTV calculation (ARPU / churn_rate)
                # where churn_rate is the number of churned customers / number of customers
                ast.Alias(
                    alias="ltv",
                    expr=ast.Call(
                        name="multiIf",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["customer_count"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.Call(
                                name="toDecimal",
                                args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["churned_customer_count"]),
                                right=ast.Constant(value=0),
                            ),
                            ast.Constant(value=None),
                            ast.Call(
                                name="divideDecimal",
                                args=[
                                    ast.Field(chain=["arpu"]),
                                    ast.Call(
                                        name="toDecimal",
                                        args=[
                                            ast.Call(
                                                name="divide",
                                                args=[
                                                    ast.Field(chain=["churned_customer_count"]),
                                                    ast.Field(chain=["customer_count"]),
                                                ],
                                            ),
                                            ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                                        ],
                                    ),
                                ],
                            ),
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

    def _get_subquery(
        self,
        subscription_view: RevenueAnalyticsBaseView,
        revenue_item_view: Optional[RevenueAnalyticsBaseView],
    ) -> ast.SelectQuery:
        with self.timings.measure("subquery"):
            dates_expr = self._dates_expr()

        join_expr = ast.JoinExpr(
            alias=RevenueAnalyticsSubscriptionView.get_generic_view_alias(),
            table=ast.Field(chain=[subscription_view.name]),
        )

        if revenue_item_view is not None:
            join_expr.next_join = ast.JoinExpr(
                alias=RevenueAnalyticsRevenueItemView.get_generic_view_alias(),
                table=ast.Field(chain=[revenue_item_view.name]),
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "id"]),
                        right=ast.Field(
                            chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "subscription_id"]
                        ),
                    ),
                ),
            )

        query = ast.SelectQuery(
            select=[
                self._build_breakdown_expr(
                    "breakdown_by",
                    ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "source_label"]),
                    subscription_view,
                ),
                ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "customer_id"]),
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
                # Revenue data for ARPU/LTV calculation
                ast.Alias(
                    alias="revenue",
                    expr=ast.Call(
                        name="sumIf",
                        args=[
                            ast.Field(chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "amount"]),
                            self._period_eq_expr(
                                ast.Field(
                                    chain=[RevenueAnalyticsRevenueItemView.get_generic_view_alias(), "timestamp"]
                                ),
                                ast.Field(chain=["period_start"]),
                            ),
                        ],
                    ),
                ),
            ],
            select_from=self._with_where_property_and_breakdown_joins(join_expr, subscription_view),
            group_by=[
                ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "customer_id"]),
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["period_start"]),
            ],
            order_by=[
                ast.OrderExpr(
                    expr=ast.Field(chain=[RevenueAnalyticsSubscriptionView.get_generic_view_alias(), "customer_id"]),
                    order="ASC",
                ),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
            ],
        )

        # We can't simply attach a list with less than 2 expressions to an `And` node, so we need to be more careful here
        where_exprs = self.where_property_exprs(subscription_view)
        if len(where_exprs) == 1:
            query.where = where_exprs[0]
        elif len(where_exprs) > 1:
            query.where = ast.And(exprs=where_exprs)

        return query

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
                "breakdown": {
                    "property": breakdown,
                    "kind": kind,
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

    def _calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_metrics_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsMetricsQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
