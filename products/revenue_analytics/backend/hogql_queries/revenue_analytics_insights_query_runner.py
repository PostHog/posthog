from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQuery,
)
from posthog.utils import format_label_date

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner

NO_PRODUCT_PLACEHOLDER = "<none>"


class RevenueAnalyticsInsightsQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsInsightsQuery
    response: RevenueAnalyticsInsightsQueryResponse
    cached_response: CachedRevenueAnalyticsInsightsQueryResponse

    def to_query(self) -> ast.SelectQuery:
        subqueries = self._get_subqueries()
        if subqueries is None:
            return ast.SelectQuery.empty()

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="value", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
                ast.Alias(alias="day_start", expr=ast.Field(chain=["day_start"])),
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["breakdown_by"])),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectSetQuery.create_from_queries(subqueries, set_operator="UNION ALL"),
            ),
            group_by=[ast.Field(chain=["day_start"]), ast.Field(chain=["breakdown_by"])],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
        )

    def _get_subqueries(self) -> list[ast.SelectQuery]:
        if self.query.groupBy == "all":
            return self._get_subqueries_by_all()
        elif self.query.groupBy == "product":
            return self._get_subqueries_by_product()
        elif self.query.groupBy == "cohort":
            pass  # TODO: Implement this

        raise ValueError(f"Invalid group by: {self.query.groupBy}")

    def _get_subqueries_by_all(self) -> list[ast.SelectQuery] | None:
        queries = []
        for view_name, selects in self.revenue_selects().items():
            if selects["charge"] is None:
                continue

            queries.append(
                ast.SelectQuery(
                    select=[
                        ast.Alias(alias="breakdown_by", expr=ast.Constant(value=view_name)),
                        ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                        ast.Alias(
                            alias="day_start",
                            expr=ast.Call(
                                name=f"toStartOf{self.query_date_range.interval_name.title()}",
                                args=[ast.Field(chain=["timestamp"])],
                            ),
                        ),
                    ],
                    select_from=ast.JoinExpr(table=selects["charge"]),
                    where=self.timestamp_where_clause(),
                )
            )

        if len(queries) == 0:
            return None
        return queries

    def _get_subqueries_by_product(self) -> list[ast.SelectQuery] | None:
        queries = []
        for view_name, selects in self.revenue_selects().items():
            if selects["charge"] is None:
                continue

            query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="breakdown_by", expr=ast.Constant(value=view_name)),
                    ast.Alias(alias="amount", expr=ast.Field(chain=["charge", "amount"])),
                    ast.Alias(
                        alias="day_start",
                        expr=ast.Call(
                            name=f"toStartOf{self.query_date_range.interval_name.title()}",
                            args=[ast.Field(chain=["charge", "timestamp"])],
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(alias="charge", table=selects["charge"]),
                where=self.timestamp_where_clause(),
            )

            # Join with item to get access to the product name
            # and also change the `breakdown_by` to include the `product_name`
            if selects["item"] is not None:
                if query.select and query.select[0] and isinstance(query.select[0], ast.Alias):  # Make mypy happy
                    query.select[0].expr = ast.Call(
                        name="concat",
                        args=[
                            ast.Constant(value=view_name),
                            ast.Constant(value=" - "),
                            ast.Call(
                                name="coalesce",
                                args=[
                                    ast.Field(chain=["item", "product_name"]),
                                    ast.Constant(value=NO_PRODUCT_PLACEHOLDER),
                                ],
                            ),
                        ],
                    )

                if query.select_from is not None:
                    query.select_from.next_join = ast.JoinExpr(
                        table=selects["item"],
                        alias="item",
                        join_type="LEFT JOIN",
                        constraint=ast.JoinConstraint(
                            constraint_type="ON",
                            expr=ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["charge", "invoice_id"]),
                                right=ast.Field(chain=["item", "id"]),
                            ),
                        ),
                    )

            queries.append(query)

        if len(queries) == 0:
            return None
        return queries

    def calculate(self):
        query = self.to_query()
        if query is None:
            return RevenueAnalyticsInsightsQueryResponse(
                results=[],
                modifiers=self.modifiers,
            )

        response = execute_hogql_query(
            query_type="revenue_analytics_insights_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # We want the result to look just like the Insights query results look like to simplify our UI
        # First, let's generate all of the dates/labels because they'll be exactly the same for all of the results
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range.interval_name) for item in all_dates]

        # We can also group the results we have by a tuple of (breakdown_by, day_start)
        # This will allow us to easily query the results by breakdown_by and day_start
        # and then we can just add the data to the results
        # [0, 1, 2] -> [value, day_start, breakdown_by]
        grouped_results = {}
        breakdowns = set()
        for value, day_start, breakdown_by in response.results:
            breakdowns.add(breakdown_by)
            grouped_results[(breakdown_by, day_start.strftime("%Y-%m-%d"))] = value

        results = []
        for breakdown in breakdowns:
            results.append(
                {
                    "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                    "data": [grouped_results.get((breakdown, day), 0) for day in days],
                    "days": days,
                    "label": breakdown,
                    "labels": labels,
                }
            )

        return RevenueAnalyticsInsightsQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
