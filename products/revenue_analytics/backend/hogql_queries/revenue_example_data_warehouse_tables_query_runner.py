from typing import cast, Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql.database.database import create_hogql_database, Database
from posthog.hogql.hogql import HogQLContext
from posthog.schema import (
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
    CachedRevenueExampleDataWarehouseTablesQueryResponse,
)
from ..models import RevenueAnalyticsRevenueView


class RevenueExampleDataWarehouseTablesQueryRunner(QueryRunner):
    query: RevenueExampleDataWarehouseTablesQuery
    response: RevenueExampleDataWarehouseTablesQueryResponse
    cached_response: CachedRevenueExampleDataWarehouseTablesQueryResponse
    paginator: HogQLHasMorePaginator
    database: Database
    hogql_context: HogQLContext

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

        # We create a new context here because we need to access the database
        # below in the to_query method and creating a database is pretty heavy
        # so we'll reuse this database for the query once it eventually runs
        self.database = create_hogql_database(team=self.team)
        self.hogql_context = HogQLContext(team_id=self.team.pk, database=self.database)

    def to_query(self) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        queries = []

        # UNION ALL for all of the `RevenueAnalyticsRevenueView`s
        for view_name in self.database.get_views():
            view = self.database.get_table(view_name)
            if isinstance(view, RevenueAnalyticsRevenueView):
                view = cast(RevenueAnalyticsRevenueView, view)

                queries.append(
                    ast.SelectQuery(
                        select=[
                            ast.Alias(alias="view_name", expr=ast.Constant(value=view_name)),
                            ast.Alias(alias="distinct_id", expr=ast.Field(chain=[view_name, "id"])),
                            ast.Alias(
                                alias="original_revenue", expr=ast.Field(chain=[view_name, "adjusted_original_amount"])
                            ),
                            ast.Alias(
                                alias="original_currency", expr=ast.Field(chain=[view_name, "original_currency"])
                            ),
                            ast.Alias(alias="revenue", expr=ast.Field(chain=[view_name, "amount"])),
                            ast.Alias(alias="currency", expr=ast.Field(chain=[view_name, "currency"])),
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
                        order_by=[ast.OrderExpr(expr=ast.Field(chain=[view_name, "timestamp"]), order="DESC")],
                    )
                )

        # If no queries, return a select with no results
        if len(queries) == 0:
            return ast.SelectQuery.empty()

        if len(queries) == 1:
            return queries[0]

        return ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL")

    def calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="revenue_example_external_tables_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            hogql_context=self.hogql_context,
        )

        return RevenueExampleDataWarehouseTablesQueryResponse(
            columns=response.columns,
            results=response.results,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
