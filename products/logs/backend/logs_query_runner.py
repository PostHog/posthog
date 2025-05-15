from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import CachedLogsQueryResponse, LogsQuery, LogsQueryResponse


class LogsQueryRunner(QueryRunner):
    query: LogsQuery
    response: LogsQueryResponse
    cached_response: CachedLogsQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

    def calculate(self) -> LogsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.ONLINE,
            timings=self.timings,
            limit_context=self.limit_context,
        )

        return LogsQueryResponse(results=response.results, **self.paginator.response_params())

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self.select(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["logs"])),
            where=self.where(),
            order_by=self.query.orderBy,
        )

    def select(self) -> list[ast.Expr]:
        return [
            ast.Field(chain=["uuid"]),
            ast.Field(chain=["trace_id"]),
            ast.Field(chain=["span_id"]),
            ast.Field(chain=["body"]),
            ast.Field(chain=["attributes"]),
            ast.Field(chain=["timestamp"]),
            ast.Field(chain=["observed_timestamp"]),
            ast.Field(chain=["severity_text"]),
            ast.Field(chain=["resource"]),
        ]

    def where(self):
        exprs: list[ast.Expr] = []

        if self.query.searchTerm is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Call(
                        name="position",
                        args=[
                            ast.Call(name="lower", args=[ast.Field(chain=["body"])]),
                            ast.Call(name="lower", args=[ast.Constant(value=self.query.searchTerm)]),
                        ],
                    ),
                    right=ast.Constant(value=0),
                )
            )

        if self.query.resource is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["resource"]),
                    right=ast.Constant(value=self.query.resource),
                )
            )

        if (self.query.severityLevels) > 0:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["severity_level"]),
                    right=ast.Constant(value=self.query.severityLevels),
                )
            )

        return ast.Or(exprs=exprs)
