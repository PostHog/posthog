from collections import defaultdict
from datetime import datetime
from typing import Union
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext
from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsInsightsQuery,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsTopCustomersQuery,
)
from ..views.revenue_analytics_base_view import RevenueAnalyticsBaseView
from ..views.revenue_analytics_charge_view import RevenueAnalyticsChargeView
from ..views.revenue_analytics_customer_view import RevenueAnalyticsCustomerView
from ..views.revenue_analytics_item_view import RevenueAnalyticsItemView

# If we are running a query that has no date range ("all"/all time),
# we use this as a fallback for the earliest timestamp that we have data for
EARLIEST_TIMESTAMP = datetime.fromisoformat("2015-01-01T00:00:00Z")


# Base class, empty for now but might include some helpers in the future
class RevenueAnalyticsQueryRunner(QueryRunnerWithHogQLContext):
    query: Union[
        RevenueAnalyticsGrowthRateQuery,
        RevenueAnalyticsInsightsQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
    ]

    def revenue_selects(
        self,
    ) -> dict[str, dict[str, ast.SelectQuery | None]]:
        selects = defaultdict(lambda: {"charge": None, "customer": None, "item": None})

        for view_name in self.database.get_views():
            view = self.database.get_table(view_name)

            if isinstance(view, RevenueAnalyticsBaseView):
                if view.source_id is not None and view.source_id in self.query.revenueSources.dataWarehouseSources:
                    select = ast.SelectQuery(
                        select=[ast.Field(chain=["*"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                    )

                    if isinstance(view, RevenueAnalyticsChargeView):
                        selects[view.prefix]["charge"] = select
                    elif isinstance(view, RevenueAnalyticsCustomerView):
                        selects[view.prefix]["customer"] = select
                    elif isinstance(view, RevenueAnalyticsItemView):
                        selects[view.prefix]["item"] = select
                elif view.source_id is None and isinstance(view, RevenueAnalyticsChargeView):
                    if len(self.query.revenueSources.events) > 0:
                        select = ast.SelectQuery(
                            select=[ast.Field(chain=["*"])],
                            select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                            where=ast.Call(
                                name="in",
                                args=[
                                    ast.Field(chain=["event_name"]),
                                    ast.Constant(value=self.query.revenueSources.events),
                                ],
                            ),
                        )
                        selects[view.prefix]["charge"] = select

        return selects

    def revenue_subqueries(
        self,
    ) -> tuple[ast.SelectSetQuery | None, ast.SelectSetQuery | None, ast.SelectSetQuery | None]:
        revenue_selects = self.revenue_selects()

        # Remove the view name because it's not useful for the select query
        parsed_charge_selects = [
            selects["charge"] for _, selects in revenue_selects.items() if selects["charge"] is not None
        ]
        parsed_customer_selects = [
            selects["customer"] for _, selects in revenue_selects.items() if selects["customer"] is not None
        ]
        parsed_item_selects = [selects["item"] for _, selects in revenue_selects.items() if selects["item"] is not None]

        return (
            ast.SelectSetQuery.create_from_queries(parsed_charge_selects, set_operator="UNION ALL")
            if parsed_charge_selects
            else None,
            ast.SelectSetQuery.create_from_queries(parsed_customer_selects, set_operator="UNION ALL")
            if parsed_customer_selects
            else None,
            ast.SelectSetQuery.create_from_queries(parsed_item_selects, set_operator="UNION ALL")
            if parsed_item_selects
            else None,
        )

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval if hasattr(self.query, "interval") else None,
            now=datetime.now(),
            earliest_timestamp_fallback=EARLIEST_TIMESTAMP,
        )

    def timestamp_where_clause(self) -> ast.Expr:
        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    right=self.query_date_range.date_from_as_hogql(),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["timestamp"]),
                    right=self.query_date_range.date_to_as_hogql(),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ],
        )
