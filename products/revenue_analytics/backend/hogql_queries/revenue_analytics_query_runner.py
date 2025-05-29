from datetime import datetime
from typing import Union
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql import ast
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.context import HogQLContext
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsOverviewQuery,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleEventsQuery,
)
from ..models import RevenueAnalyticsRevenueView, CHARGE_REVENUE_VIEW_SUFFIX, CUSTOMER_REVENUE_VIEW_SUFFIX


# Base class, empty for now but might include some helpers in the future
class RevenueAnalyticsQueryRunner(QueryRunner):
    query: Union[
        RevenueAnalyticsTopCustomersQuery,
        RevenueAnalyticsGrowthRateQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueExampleDataWarehouseTablesQuery,
        RevenueExampleEventsQuery,
    ]
    database: Database
    hogql_context: HogQLContext

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We create a new context here because we need to access the database
        # below in the to_query method and creating a database is pretty heavy
        # so we'll reuse this database for the query once it eventually runs
        self.database = create_hogql_database(team=self.team)
        self.hogql_context = HogQLContext(team_id=self.team.pk, database=self.database)

    def revenue_subqueries(
        self,
    ) -> tuple[ast.SelectQuery | ast.SelectSetQuery | None, ast.SelectQuery | ast.SelectSetQuery | None]:
        charge_selects = []
        customer_selects = []

        for view_name in self.database.get_views():
            view = self.database.get_table(view_name)
            if isinstance(view, RevenueAnalyticsRevenueView):
                select = ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                )
                if CHARGE_REVENUE_VIEW_SUFFIX in view.name:
                    charge_selects.append(select)
                elif CUSTOMER_REVENUE_VIEW_SUFFIX in view.name:
                    customer_selects.append(select)

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
            date_range=getattr(self.query, "dateRange", None),
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def where_clause(self) -> ast.Expr:
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
                    op=ast.CompareOperationOp.Lt,
                ),
            ],
        )
