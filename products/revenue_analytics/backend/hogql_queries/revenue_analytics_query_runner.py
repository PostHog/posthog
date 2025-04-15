from datetime import datetime
from typing import Union
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql import ast
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.context import HogQLContext
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    RevenueAnalyticsChurnRateQuery,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsOverviewQuery,
)
from ..models import RevenueAnalyticsRevenueView


# Base class, empty for now but might include some helpers in the future
class RevenueAnalyticsQueryRunner(QueryRunner):
    query: Union[RevenueAnalyticsChurnRateQuery, RevenueAnalyticsGrowthRateQuery, RevenueAnalyticsOverviewQuery]
    database: Database
    hogql_context: HogQLContext

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We create a new context here because we need to access the database
        # below in the to_query method and creating a database is pretty heavy
        # so we'll reuse this database for the query once it eventually runs
        self.database = create_hogql_database(team=self.team)
        self.hogql_context = HogQLContext(team_id=self.team.pk, database=self.database)

    def all_revenue_views(self) -> ast.JoinExpr | None:
        selects = []
        for view_name in self.database.get_views():
            view = self.database.get_table(view_name)
            if isinstance(view, RevenueAnalyticsRevenueView):
                selects.append(
                    ast.SelectQuery(
                        select=[ast.Field(chain=["*"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                    )
                )

        if len(selects) == 0:
            return None

        if len(selects) == 1:
            return ast.JoinExpr(table=selects[0])

        return ast.JoinExpr(table=ast.SelectSetQuery.create_from_queries(selects, set_operator="UNION ALL"))

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
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
