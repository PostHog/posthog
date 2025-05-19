from datetime import datetime
from typing import Union
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext
from posthog.hogql import ast
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsOverviewQuery,
)
from ..views.revenue_analytics_base_view import RevenueAnalyticsBaseView
from ..views.revenue_analytics_charge_view import RevenueAnalyticsChargeView
from ..views.revenue_analytics_customer_view import RevenueAnalyticsCustomerView

# If we are running a query that has no date range ("all"/all time),
# we use this as a fallback for the earliest timestamp that we have data for
EARLIEST_TIMESTAMP = datetime.fromisoformat("2015-01-01T00:00:00Z")


# Base class, empty for now but might include some helpers in the future
class RevenueAnalyticsQueryRunner(QueryRunnerWithHogQLContext):
    query: Union[
        RevenueAnalyticsTopCustomersQuery,
        RevenueAnalyticsGrowthRateQuery,
        RevenueAnalyticsOverviewQuery,
    ]

    def revenue_subqueries(
        self,
    ) -> tuple[ast.SelectQuery | ast.SelectSetQuery | None, ast.SelectQuery | ast.SelectSetQuery | None]:
        charge_selects = []
        customer_selects = []

        for view_name in self.database.get_views():
            view = self.database.get_table(view_name)

            if isinstance(view, RevenueAnalyticsBaseView):
                if view.source_id is not None and view.source_id in self.query.revenueSources.dataWarehouseSources:
                    select = ast.SelectQuery(
                        select=[ast.Field(chain=["*"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                    )

                    if isinstance(view, RevenueAnalyticsChargeView):
                        charge_selects.append(select)
                    elif isinstance(view, RevenueAnalyticsCustomerView):
                        customer_selects.append(select)
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
                        charge_selects.append(select)

        charge_subquery: ast.SelectQuery | ast.SelectSetQuery | None = None
        if len(charge_selects) == 1:
            charge_subquery = charge_selects[0]
        elif len(charge_selects) > 1:
            charge_subquery = ast.SelectSetQuery.create_from_queries(charge_selects, set_operator="UNION ALL")

        customer_subquery: ast.SelectQuery | ast.SelectSetQuery | None = None
        if len(customer_selects) == 1:
            customer_subquery = customer_selects[0]
        elif len(customer_selects) > 1:
            customer_subquery = ast.SelectSetQuery.create_from_queries(customer_selects, set_operator="UNION ALL")

        return (charge_subquery, customer_subquery)

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
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
