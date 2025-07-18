from decimal import Decimal

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    HogQLQueryResponse,
    CachedRevenueAnalyticsArpuQueryResponse,
    RevenueAnalyticsArpuQueryResponse,
    RevenueAnalyticsArpuQuery,
)
from posthog.models.filters.mixins.utils import cached_property
from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from products.revenue_analytics.backend.views import RevenueAnalyticsInvoiceItemView


class RevenueAnalyticsArpuQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsArpuQuery
    response: RevenueAnalyticsArpuQueryResponse
    cached_response: CachedRevenueAnalyticsArpuQueryResponse

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("revenue_subquery"):
            revenue_subquery = self._revenue_subquery()
            if revenue_subquery is None:
                return ast.SelectQuery.empty(columns=["breakdown_by", "period_start", "value"])

        with self.timings.measure("customer_count_subquery"):
            customer_count_subquery = self._customer_count_subquery()
            if customer_count_subquery is None:
                return ast.SelectQuery.empty(columns=["breakdown_by", "period_start", "value"])

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["revenue", "breakdown_by"])),
                ast.Alias(alias="period_start", expr=ast.Field(chain=["revenue", "period_start"])),
                ast.Alias(
                    alias="value",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.Or(
                                exprs=[
                                    ast.Call(name="isNull", args=[ast.Field(chain=["customer_count", "count"])]),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["customer_count", "count"]),
                                        right=ast.Constant(value=0),
                                    ),
                                ],
                            ),
                            ast.Constant(value=0),
                            ast.Call(
                                name="divide",
                                args=[
                                    ast.Field(chain=["revenue", "amount"]),
                                    ast.Field(chain=["customer_count", "count"]),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                alias="revenue",
                table=revenue_subquery,
                next_join=ast.JoinExpr(
                    alias="customer_count",
                    table=customer_count_subquery,
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["revenue", "period_start"]),
                                    right=ast.Field(chain=["customer_count", "period_start"]),
                                ),
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["revenue", "breakdown_by"]),
                                    right=ast.Field(chain=["customer_count", "breakdown_by"]),
                                ),
                            ],
                        ),
                    ),
                ),
            ),
            # Return sorted by period_start/day_start, and then for each individual day we put the maximum first (value)
            # This will allow us to return the list sorted according to the numbers in the first day
            # Finally sort by breakdown_by for the rare cases where they tie (usually at 0 revenue)
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["value"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
            # Need a huge limit because we need (dates x breakdown)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

    # NOTE: This is simply revenue in the current period and not the MRR
    # We might wanna let customers choose between MRR and revenue in the future
    def _revenue_subquery(self) -> ast.SelectQuery | None:
        if self.revenue_subqueries.invoice_item is None:
            return None

        with self.timings.measure("dates_expr"):
            dates_expr = self._dates_expr()

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(alias="period_start", expr=dates_expr),
                ast.Alias(alias="amount", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
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
                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    *self.where_property_exprs,
                ]
            ),
            group_by=[ast.Field(chain=["breakdown_by"]), ast.Field(chain=["period_start"])],
        )

        # Limit to 2 group bys at most for performance reasons
        # This is also implemented in the frontend, but let's guarantee it here too
        with self.timings.measure("append_group_by"):
            for group_by in self.query.groupBy[:2]:
                query = self._append_group_by(query, RevenueAnalyticsInvoiceItemView, group_by)

        return query

    def _customer_count_subquery(self) -> ast.SelectQuery | None:
        if self.revenue_subqueries.customer is None:
            return None

        with self.timings.measure("dates_expr"):
            dates_expr = self._dates_expr()

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(alias="period_start", expr=dates_expr),
                ast.Alias(
                    alias="count",
                    expr=ast.Call(
                        name="countIf",
                        distinct=True,
                        args=[
                            ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "customer_id"]),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Call(
                                    name=f"toStartOf{self.query_date_range.interval_name.title()}",
                                    args=[
                                        ast.Field(
                                            chain=[
                                                RevenueAnalyticsInvoiceItemView.get_generic_view_alias(),
                                                "timestamp",
                                            ]
                                        ),
                                    ],
                                ),
                                right=ast.Field(chain=["period_start"]),
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
            group_by=[
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["period_start"]),
            ],
            where=ast.And(
                exprs=[
                    self.timestamp_where_clause(
                        [RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"]
                    ),
                    *self._parsed_where_property_exprs,
                ]
            ),
        )

        # Limit to 2 group bys at most for performance reasons
        # This is also implemented in the frontend, but let's guarantee it here too
        with self.timings.measure("append_group_by"):
            for group_by in self.query.groupBy[:2]:
                query = self._append_group_by(query, RevenueAnalyticsInvoiceItemView, group_by)

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
        for breakdown_by, period_start, count in response.results:
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)

            grouped_results[(breakdown_by, period_start.strftime("%Y-%m-%d"))] = count

        return [
            {
                "action": {
                    "days": all_dates,
                    "id": breakdown,
                    "name": breakdown,
                },
                "data": [grouped_results.get((breakdown, day), 0) for day in days],
                "days": days,
                "label": breakdown,
                "labels": labels,
            }
            for breakdown in breakdowns
        ]

    def calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_arpu_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsArpuQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
