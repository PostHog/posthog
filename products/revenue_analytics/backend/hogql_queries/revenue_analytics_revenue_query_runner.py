from collections import defaultdict
from decimal import Decimal
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    HogQLQueryResponse,
    CachedRevenueAnalyticsRevenueQueryResponse,
    RevenueAnalyticsRevenueQueryResponse,
    RevenueAnalyticsRevenueQuery,
    RevenueAnalyticsRevenueQueryResult,
    ResolvedDateRangeResponse,
)
from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from .revenue_analytics_query_runner import (
    RevenueAnalyticsQueryRunner,
)
from products.revenue_analytics.backend.views import RevenueAnalyticsInvoiceItemView

LOOKBACK_PERIOD_DAYS = 30
LOOKBACK_PERIOD = timedelta(days=LOOKBACK_PERIOD_DAYS)


class RevenueAnalyticsRevenueQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsRevenueQuery
    response: RevenueAnalyticsRevenueQueryResponse
    cached_response: CachedRevenueAnalyticsRevenueQueryResponse

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("subquery"):
            subquery = self._get_subquery()
            if subquery is None:
                return ast.SelectQuery.empty(
                    columns=[
                        "value",
                        "day_start",
                        "period_start",
                        "is_recurring",
                        "breakdown_by",
                    ]
                )

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="value", expr=ast.Call(name="sum", args=[ast.Field(chain=["amount"])])),
                ast.Alias(alias="day_start", expr=ast.Field(chain=["day_start"])),
                ast.Alias(alias="period_start", expr=ast.Field(chain=["period_start"])),
                ast.Alias(alias="is_recurring", expr=ast.Field(chain=["is_recurring"])),
                ast.Alias(alias="breakdown_by", expr=ast.Field(chain=["breakdown_by"])),
            ],
            select_from=ast.JoinExpr(table=subquery),
            group_by=[
                ast.Field(chain=["day_start"]),
                ast.Field(chain=["period_start"]),
                ast.Field(chain=["breakdown_by"]),
                ast.Field(chain=["is_recurring"]),
            ],
            # Return sorted by period_start/day_start, and then for each individual day we put the maximum first (value)
            # This will allow us to return the list sorted according to the numbers in the first day
            # Finally sort by breakdown_by for the rare cases where they tie (usually at 0 revenue)
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["period_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["day_start"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["value"]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_by"]), order="ASC"),
            ],
            # Need a huge limit because we need (dates x breakdown)-many rows to be returned
            limit=ast.Constant(value=10000),
        )

    def _get_subquery(self) -> ast.SelectQuery | None:
        if self.revenue_subqueries.invoice_item is None:
            return None

        query = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_by",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "source_label"]),
                ),
                ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                ast.Alias(
                    alias="is_recurring",
                    expr=ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "is_recurring"]),
                ),
                ast.Alias(
                    alias="day_start",
                    expr=ast.Call(
                        name=f"toStartOfDay",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
                    ),
                ),
                ast.Alias(
                    alias="period_start",
                    expr=ast.Call(
                        name=f"toStartOf{self.query_date_range.interval_name.title()}",
                        args=[ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"])],
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
                        chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "timestamp"],
                        extra_days_before=LOOKBACK_PERIOD_DAYS,  # Add extra days to ensure MRR calculations are correct
                    ),
                    *self.where_property_exprs,
                ]
            ),
        )

        # Limit to 2 group bys at most for performance reasons
        # This is also implemented in the frontend, but let's guarantee it here too
        with self.timings.measure("append_group_by"):
            for group_by in self.query.groupBy[:2]:
                query = self._append_group_by(query, RevenueAnalyticsInvoiceItemView, group_by)

        return query

    def _build_results(self, response: HogQLQueryResponse) -> RevenueAnalyticsRevenueQueryResult:
        # We want the result to look just like the Insights query results look like to simplify our UI
        # First, let's generate all of the dates/labels because they'll be exactly the same for all of the results
        all_dates = self.query_date_range.all_values()
        days = [date.strftime("%Y-%m-%d") for date in all_dates]
        labels = [format_label_date(item, self.query_date_range, self.team.week_start_day) for item in all_dates]

        # We can also group the results we have by a tuple of (breakdown_by, period_start)
        # This will allow us to easily query the results by breakdown_by and period_start
        # and then we can just add the data to the results
        # [0, 1, 2] -> [value, period_start, breakdown_by]
        grouped_results: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
        breakdowns = []
        for value, _day_start, period_start, _is_recurring, breakdown_by in response.results:
            # Use array to guarantee insertion order
            if breakdown_by not in breakdowns:
                breakdowns.append(breakdown_by)
            grouped_results[(breakdown_by, period_start.strftime("%Y-%m-%d"))] += value

        gross_results = [
            {
                "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                "data": [grouped_results.get((breakdown, day), 0) for day in days],
                "days": days,
                "label": breakdown,
                "labels": labels,
            }
            for breakdown in breakdowns
        ]

        # Group recurring results by breakdown and sort by day_start
        recurring_by_breakdown: defaultdict[str, list[tuple[datetime, Decimal]]] = defaultdict(list)
        for value, day_start, _period_start, is_recurring, breakdown_by in response.results:
            if is_recurring:
                recurring_by_breakdown[breakdown_by].append((day_start.date(), value))

        # For each breakdown, calculate MRR using pointer race
        mrr_results = []
        for breakdown in breakdowns:
            events = recurring_by_breakdown[breakdown]
            events.sort(key=lambda x: x[0])

            # Pointer race algorithm
            start_ptr = 0  # Points to oldest subscription in window
            end_ptr = 0  # Points to next subscription to add
            accumulator = Decimal(0)
            mrr_data: list[Decimal] = []

            # Process each day in our result set
            for day in days:
                day_date = datetime.strptime(day, "%Y-%m-%d").date()
                lookback_until = day_date - LOOKBACK_PERIOD

                # Move start pointer: remove subscriptions older than 30 days
                while start_ptr < len(events) and events[start_ptr][0] < lookback_until:
                    accumulator -= events[start_ptr][1]
                    start_ptr += 1

                # Move end pointer: add subscriptions up to current day
                while end_ptr < len(events) and events[end_ptr][0] <= day_date:
                    accumulator += events[end_ptr][1]
                    end_ptr += 1

                mrr_data.append(accumulator)

            mrr_results.append(
                {
                    "action": {"days": all_dates, "id": breakdown, "name": breakdown},
                    "data": mrr_data,
                    "days": days,
                    "label": breakdown,
                    "labels": labels,
                }
            )

        return RevenueAnalyticsRevenueQueryResult(gross=gross_results, mrr=mrr_results)

    def calculate(self):
        with self.timings.measure("to_query"):
            query = self.to_query()

        with self.timings.measure("execute_hogql_query"):
            response = execute_hogql_query(
                query_type="revenue_analytics_revenue_query",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        with self.timings.measure("build_results"):
            results = self._build_results(response)

        return RevenueAnalyticsRevenueQueryResponse(
            results=results,
            hogql=response.hogql,
            modifiers=self.modifiers,
            resolved_date_range=ResolvedDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
            ),
        )
