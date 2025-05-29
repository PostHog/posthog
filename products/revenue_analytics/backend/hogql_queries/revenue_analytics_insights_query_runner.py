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

    def to_query(self) -> ast.SelectQuery | None:
        subqueries = self._get_subqueries()
        if subqueries is None:
            return None

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
            # Return sorted by day_start, and then for each individual day we put the maximum first
            # This will allow us to return the list sorted according to the numbers in the last day
            # Finally sort by breakdown_by for the rare cases where they tie (usually at 0 revenue)
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["value"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
            limit=ast.Constant(
                value=10000
            ),  # Need a huge limit because we need (dates x products)-many rows to be returned
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
        queries: list[ast.SelectQuery] = []
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
        queries: list[ast.SelectQuery] = []
        for view_name, selects in self.revenue_selects().items():
            if selects["charge"] is None:
                continue

            charge_alias = f"charge_{view_name}"

            query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="breakdown_by", expr=ast.Constant(value=view_name)),
                    ast.Alias(alias="amount", expr=ast.Field(chain=[charge_alias, "amount"])),
                    ast.Alias(
                        alias="day_start",
                        expr=ast.Call(
                            name=f"toStartOf{self.query_date_range.interval_name.title()}",
                            args=[ast.Field(chain=[charge_alias, "timestamp"])],
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(alias=charge_alias, table=selects["charge"]),
                where=self.timestamp_where_clause(chain=[charge_alias, "timestamp"]),
            )

            # Join with invoice and product to get access to the `product_name``
            # and also change the `breakdown_by` to include that
            if selects["invoice_item"] is not None and selects["product"] is not None:
                invoice_item_alias = f"invoice_item_{view_name}"
                product_alias = f"product_{view_name}"

                # If checks to make mypy happy
                if (
                    query.select
                    and query.select[0]
                    and isinstance(query.select[0], ast.Alias)
                    and query.select[0].alias == "breakdown_by"
                ):  # Make mypy happy
                    query.select[0].expr = ast.Call(
                        name="concat",
                        args=[
                            ast.Constant(value=view_name),
                            ast.Constant(value=" - "),
                            ast.Call(
                                name="coalesce",
                                args=[
                                    ast.Field(chain=[product_alias, "name"]),
                                    ast.Constant(value=NO_PRODUCT_PLACEHOLDER),
                                ],
                            ),
                        ],
                    )

                if (
                    query.select
                    and query.select[1]
                    and isinstance(query.select[1], ast.Alias)
                    and query.select[1].alias == "amount"
                ):
                    query.select[1].expr = ast.Alias(
                        alias="amount", expr=ast.Field(chain=[invoice_item_alias, "amount"])
                    )

                if query.select_from is not None:
                    query.select_from.next_join = ast.JoinExpr(
                        table=selects["invoice_item"],
                        alias=invoice_item_alias,
                        join_type="LEFT OUTER JOIN",
                        constraint=ast.JoinConstraint(
                            constraint_type="ON",
                            expr=ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=[charge_alias, "invoice_id"]),
                                right=ast.Field(chain=[invoice_item_alias, "id"]),
                            ),
                        ),
                        next_join=ast.JoinExpr(
                            table=selects["product"],
                            alias=product_alias,
                            join_type="LEFT OUTER JOIN",
                            constraint=ast.JoinConstraint(
                                constraint_type="ON",
                                expr=ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=[invoice_item_alias, "product_id"]),
                                    right=ast.Field(chain=[product_alias, "id"]),
                                ),
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
            query=query,
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
        breakdowns = []
        for value, day_start, breakdown_by in response.results:
            # Use array to guarantee insertion order
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)
            grouped_results[(breakdown_by, day_start.strftime("%Y-%m-%d"))] = value

        results = [
            {
                "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                "data": [grouped_results.get((breakdown, day), 0) for day in days],
                "days": days,
                "label": breakdown,
                "labels": labels,
            }
            for breakdown in breakdowns
        ]

        return RevenueAnalyticsInsightsQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
