import datetime
from zoneinfo import ZoneInfo

import structlog

from posthog.schema import (
    CachedErrorTrackingBreakdownsQueryResponse,
    ErrorTrackingBreakdownsQuery,
    ErrorTrackingBreakdownsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.queries.trends.breakdown import BREAKDOWN_NULL_STRING_LABEL
from posthog.utils import relative_date_parse

logger = structlog.get_logger(__name__)


class ErrorTrackingBreakdownsQueryRunner(AnalyticsQueryRunner[ErrorTrackingBreakdownsQueryResponse]):
    query: ErrorTrackingBreakdownsQuery
    cached_response: CachedErrorTrackingBreakdownsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.date_from = self.parse_relative_date_from(self.query.dateRange.date_from if self.query.dateRange else None)
        self.date_to = self.parse_relative_date_to(self.query.dateRange.date_to if self.query.dateRange else None)

    @classmethod
    def parse_relative_date_from(cls, date: str | None) -> datetime.datetime:
        if date == "all" or date is None:
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=7)

        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")

        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def to_query(self) -> ast.SelectQuery:
        array_elements: list[ast.Expr] = []
        for prop in self.query.breakdownProperties:
            tuple_elements = [
                ast.Constant(value=prop),
                ast.Call(
                    name="ifNull",
                    args=[
                        ast.Call(name="toString", args=[ast.Field(chain=["properties", prop])]),
                        ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                    ],
                ),
            ]
            array_elements.append(ast.Tuple(exprs=tuple_elements))

        tuples_select = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_tuple",
                    expr=ast.Call(name="arrayJoin", args=[ast.Array(exprs=array_elements)]),
                )
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self.tuples_select_where(),
        )

        tuples_unpack_select = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="breakdown_property",
                    expr=ast.Call(
                        name="tupleElement", args=[ast.Field(chain=["breakdown_tuple"]), ast.Constant(value=1)]
                    ),
                ),
                ast.Alias(
                    alias="breakdown_value",
                    expr=ast.Call(
                        name="tupleElement", args=[ast.Field(chain=["breakdown_tuple"]), ast.Constant(value=2)]
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=tuples_select),
        )

        with_total_count_select = ast.SelectQuery(
            select=[
                ast.Field(chain=["breakdown_property"]),
                ast.Field(chain=["breakdown_value"]),
                ast.Alias(alias="count", expr=ast.Call(name="count", args=[])),
                ast.Alias(
                    alias="total_count",
                    expr=ast.WindowFunction(
                        name="sum",
                        args=[ast.Field(chain=["count"])],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["breakdown_property"])],
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=tuples_unpack_select),
            group_by=[ast.Field(chain=["breakdown_property"]), ast.Field(chain=["breakdown_value"])],
        )

        with_row_number_select = ast.SelectQuery(
            select=[
                ast.Field(chain=["breakdown_property"]),
                ast.Field(chain=["breakdown_value"]),
                ast.Field(chain=["count"]),
                ast.Field(chain=["total_count"]),
                ast.Alias(
                    alias="row_number",
                    expr=ast.WindowFunction(
                        name="row_number",
                        args=[],
                        over_expr=ast.WindowExpr(
                            partition_by=[ast.Field(chain=["breakdown_property"])],
                            order_by=[ast.OrderExpr(expr=ast.Field(chain=["count"]), order="DESC")],
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=with_total_count_select),
        )

        limit_value = self.query.maxValuesPerProperty if self.query.maxValuesPerProperty is not None else 3
        final_select = ast.SelectQuery(
            select=[
                ast.Field(chain=["breakdown_property"]),
                ast.Field(chain=["breakdown_value"]),
                ast.Field(chain=["count"]),
                ast.Field(chain=["total_count"]),
            ],
            select_from=ast.JoinExpr(table=with_row_number_select),
            where=ast.CompareOperation(
                left=ast.Field(chain=["row_number"]),
                right=ast.Constant(value=limit_value),
                op=ast.CompareOperationOp.LtEq,
            ),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["breakdown_property"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["count"]), order="DESC"),
            ],
        )

        return final_select

    def tuples_select_where(self) -> ast.Expr:
        conditions: list[ast.Expr] = []

        conditions.append(
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_from),
                op=ast.CompareOperationOp.GtEq,
            )
        )
        conditions.append(
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_to),
                op=ast.CompareOperationOp.LtEq,
            )
        )

        conditions.append(
            ast.CompareOperation(
                left=ast.Field(chain=["event"]), right=ast.Constant(value="$exception"), op=ast.CompareOperationOp.Eq
            )
        )

        conditions.append(
            ast.CompareOperation(
                left=ast.Field(chain=["issue_id"]),
                right=ast.Constant(value=self.query.issueId),
                op=ast.CompareOperationOp.Eq,
            )
        )

        if self.query.filterTestAccounts:
            for prop in self.team.test_account_filters or []:
                conditions.append(property_to_expr(prop, self.team))

        return ast.And(exprs=conditions)

    def _calculate(self):
        with self.timings.measure("error_tracking_breakdowns_hogql_execute"):
            query_result = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="ErrorTrackingBreakdownsQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        grouped_results: dict[str, dict] = {}
        for row in query_result.results:
            breakdown_property = str(row[0])
            breakdown_value = str(row[1])
            count = int(row[2])
            total_count = int(row[3])

            if breakdown_property not in grouped_results:
                grouped_results[breakdown_property] = {"values": [], "total_count": total_count}

            grouped_results[breakdown_property]["values"].append({"value": breakdown_value, "count": count})

        return ErrorTrackingBreakdownsQueryResponse(
            results=grouped_results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
        )
