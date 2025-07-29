from typing import cast, Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.schema import (
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
    CachedRevenueExampleDataWarehouseTablesQueryResponse,
)
from ..views.revenue_analytics_charge_view import RevenueAnalyticsChargeView


class RevenueExampleDataWarehouseTablesQueryRunner(QueryRunnerWithHogQLContext):
    query: RevenueExampleDataWarehouseTablesQuery
    response: RevenueExampleDataWarehouseTablesQueryResponse
    cached_response: CachedRevenueExampleDataWarehouseTablesQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> Union[ast.SelectQuery, ast.SelectSetQuery]:
        queries = []

        # UNION ALL for all of the `RevenueAnalyticsChargeView`s
        for view_name in self.database.get_views():
            view = self.database.get_table(view_name)
            if isinstance(view, RevenueAnalyticsChargeView) and view.source_id is not None:
                view = cast(RevenueAnalyticsChargeView, view)

                queries.append(
                    ast.SelectQuery(
                        select=[
                            ast.Alias(alias="view_name", expr=ast.Constant(value=view_name)),
                            ast.Alias(alias="distinct_id", expr=ast.Field(chain=["id"])),
                            ast.Alias(alias="original_amount", expr=ast.Field(chain=["currency_aware_amount"])),
                            ast.Alias(alias="original_currency", expr=ast.Field(chain=["original_currency"])),
                            ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                            ast.Alias(alias="currency", expr=ast.Field(chain=["currency"])),
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
                        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                    )
                )

        # If no queries, return a select with no results
        if len(queries) == 0:
            return ast.SelectQuery.empty(
                columns=[
                    "view_name",
                    "distinct_id",
                    "original_amount",
                    "original_currency",
                    "amount",
                    "currency",
                ]
            )

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
