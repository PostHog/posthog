from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQuery,
)
from posthog.utils import format_label_date

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


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
                ast.Alias(alias="table_name", expr=ast.Field(chain=["table_name"])),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectSetQuery.create_from_queries(subqueries, set_operator="UNION ALL"),
            ),
            group_by=[ast.Field(chain=["day_start"]), ast.Field(chain=["table_name"])],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["table_name"]), order="ASC"),
            ],
        )

    def _get_subqueries(self) -> list[ast.SelectQuery] | None:
        # If there are no charge revenue views, we return a query that returns 0 for all values
        charge_selects, _, _ = self.revenue_selects()
        if not charge_selects:
            return None

        queries = []
        for view_name, charge_select in charge_selects:
            queries.append(
                ast.SelectQuery(
                    select=[
                        ast.Alias(alias="table_name", expr=ast.Constant(value=view_name)),
                        ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                        ast.Alias(
                            alias="day_start",
                            expr=ast.Call(
                                name=f"toStartOf{self.query_date_range.interval_name.title()}",
                                args=[ast.Field(chain=["timestamp"])],
                            ),
                        ),
                    ],
                    select_from=ast.JoinExpr(table=charge_select),
                    where=self.timestamp_where_clause(),
                )
            )

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

        # We can also group the results we have by a tuple of (table_name, day_start)
        # This will allow us to easily query the results by table_name and day_start
        # and then we can just add the data to the results
        # [0, 1, 2] -> [value, day_start, table_name]
        results_by_table_name_and_day_start = {}
        for result in response.results:
            results_by_table_name_and_day_start[(result[2], result[1].strftime("%Y-%m-%d"))] = result[0]

        results = []
        charge_selects, _, _ = self.revenue_selects()
        for view_name, _ in charge_selects:
            results.append(
                {
                    "action": {"days": all_dates, "id": view_name, "name": view_name},
                    "data": [results_by_table_name_and_day_start.get((view_name, day), 0) for day in days],
                    "days": days,
                    "label": view_name,
                    "labels": labels,
                }
            )

        return RevenueAnalyticsInsightsQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
        )
