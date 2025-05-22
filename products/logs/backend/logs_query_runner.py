import datetime as dt

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast

from posthog.hogql.parser import parse_select, parse_expr, parse_order_expr
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import CachedLogsQueryResponse, HogQLFilters, LogsQuery, LogsQueryResponse, IntervalType


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
            filters=HogQLFilters(dateRange=self.query.dateRange),
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
        query = parse_select("""
            SELECT
            uuid,
            trace_id,
            span_id,
            body,
            attributes,
            timestamp,
            observed_timestamp,
            severity_text,
            severity_number,
            level,
            resource,
            instrumentation_scope,
            event_name
            FROM logs
        """)

        if not isinstance(query, ast.SelectQuery):
            raise Exception("NO!")

        query.where = self.where()
        query.order_by = [parse_order_expr("timestamp ASC" if self.query.orderBy == "earliest" else "timestamp DESC")]

        return query

    def where(self):
        exprs: list[ast.Expr] = [
            ast.Placeholder(expr=ast.Field(chain=["filters"])),
        ]

        if self.query.severityLevels:
            exprs.append(
                parse_expr(
                    "severity_text IN {severityLevels}",
                    placeholders={
                        "severityLevels": ast.Tuple(
                            exprs=[ast.Constant(value=str(sl)) for sl in self.query.severityLevels]
                        )
                    },
                )
            )

        if self.query.searchTerm:
            exprs.append(
                parse_expr(
                    "body LIKE {searchTerm}",
                    placeholders={"searchTerm": ast.Constant(value=f"%{self.query.searchTerm}%")},
                )
            )

        return ast.And(exprs=exprs)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        qdr = QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=2,
            now=dt.datetime.now(),
        )

        _step = (qdr.date_to() - qdr.date_from()) / 100
        if _step < dt.timedelta(minutes=1):
            _step = dt.timedelta(minutes=1)

        _step = dt.timedelta(seconds=int(60 * round(_step.total_seconds() / 60)))
        interval_type = IntervalType.MINUTE
        interval_count = _step.total_seconds() // 60

        if _step > dt.timedelta(minutes=30):
            _step = dt.timedelta(seconds=int(3600 * round(_step.total_seconds() / 3600)))
            interval_type = IntervalType.HOUR
            interval_count = _step.total_seconds() // 3600

        if _step > dt.timedelta(days=1):
            _step = dt.timedelta(seconds=int(86400 * round(_step.total_seconds() / 86400)))
            interval_type = IntervalType.DAY
            interval_count = _step.total_seconds() // 86400

        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=interval_type,
            interval_count=int(interval_count),
            now=dt.datetime.now(),
        )
