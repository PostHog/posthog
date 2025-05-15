import datetime as dt

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
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
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            # needed for CH cloud
            settings=HogQLGlobalSettings(allow_experimental_object_type=False),
        )

        results = []
        for result in response.results:
            results.append(
                {
                    "uuid": result[0],
                    "trace_id": result[1],
                    "span_id": result[2],
                    "body": result[3],
                    "attributes": result[4],
                    "timestamp": result[5],
                    "observed_timestamp": result[6],
                    "severity_text": result[7],
                    "severity_number": result[8],
                    "level": result[9],
                    "resource": result[10],
                    "instrumentation_scope": result[11],
                    "event_name": result[12],
                }
            )

        return LogsQueryResponse(results=results, **self.paginator.response_params())

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=self.select(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["logs"])),
            where=self.where(),
            order_by=[
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"]),
                    order="ASC" if self.query.orderBy == "earliest" else "DESC",
                )
            ],
        )

    def select(self) -> list[ast.Expr]:
        return [
            ast.Alias(
                alias="uuid",
                expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])]),
            ),
            ast.Field(chain=["trace_id"]),
            ast.Field(chain=["span_id"]),
            ast.Field(chain=["body"]),
            ast.Alias(alias="attributes", expr=ast.Field(chain=["_attributes"])),
            ast.Field(chain=["timestamp"]),
            ast.Field(chain=["observed_timestamp"]),
            ast.Field(chain=["severity_text"]),
            ast.Field(chain=["severity_number"]),
            ast.Field(chain=["level"]),
            ast.Alias(alias="resource", expr=ast.Field(chain=["_resource"])),
            ast.Field(chain=["instrumentation_scope"]),
            ast.Field(chain=["event_name"]),
        ]

    def date_filter_expr(self) -> ast.Expr:
        field_to_compare = ast.Field(chain=["logs", "timestamp"])
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field_to_compare,
                    right=self.query_date_range.date_from_to_start_of_interval_hogql(),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=field_to_compare,
                    right=self.query_date_range.date_to_as_hogql(),
                ),
            ]
        )

    def where(self):
        exprs: list[ast.Expr] = []

        exprs.append(self.date_filter_expr())

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

        if len(self.query.severityLevels) > 0:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["level"]),
                    right=ast.Constant(value=[str(level) for level in self.query.severityLevels]),
                )
            )

        # TODO
        # for filter in self.query.attribute_filters:
        #     exprs.append(property_to_expr(filter, self.team))

        if len(exprs) == 0:
            return ast.Constant(value=True)
        elif len(exprs) == 1:
            return exprs[0]

        return ast.And(exprs=exprs)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=dt.datetime.now(),
        )
