from posthog.schema import (
    CachedRevenueExampleDataWarehouseTablesQueryResponse,
    DatabaseSchemaManagedViewTableKind,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.models import UnknownDatabaseField

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS


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

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        queries: list[ast.SelectQuery] = []
        views = RevenueAnalyticsQueryRunner.revenue_subqueries(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM],
            self.database,
        )
        for view in views:
            if view.is_event_view():
                continue

            queries.append(
                ast.SelectQuery(
                    select=[
                        ast.Alias(alias="view_name", expr=ast.Constant(value=view.name)),
                        ast.Alias(alias="distinct_id", expr=ast.Field(chain=["id"])),
                        ast.Alias(alias="original_amount", expr=ast.Field(chain=["currency_aware_amount"])),
                        ast.Alias(alias="original_currency", expr=ast.Field(chain=["original_currency"])),
                        ast.Alias(alias="amount", expr=ast.Field(chain=["amount"])),
                        ast.Alias(alias="currency", expr=ast.Field(chain=["currency"])),
                        ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                    order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                )
            )

        # If no queries, return a select with no results
        if len(queries) == 0:
            columns = [
                "view_name",
                "distinct_id",
                "original_amount",
                "original_currency",
                "amount",
                "currency",
                "timestamp",
            ]
            return ast.SelectQuery.empty(columns={key: UnknownDatabaseField(name=key) for key in columns})
        elif len(queries) == 1:
            return queries[0]
        else:
            # Reorder by timestamp to ensure the most recent events are at the top across all event views
            return ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.SelectSetQuery.create_from_queries(queries, "UNION ALL")),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            )

    def _calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="revenue_example_data_warehouse_tables_query",
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
