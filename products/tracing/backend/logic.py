"""
Business logic for tracing.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

import json
import base64
import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    HogQLFilters,
    IntervalType,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property

if TYPE_CHECKING:
    from posthog.models import User


class TraceSpansQueryRunner(AnalyticsQueryRunner[TraceSpansQueryResponse]):
    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, query, *args, **kwargs):
        super().__init__(query, *args, **kwargs)

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.modifiers.convertToProjectTimezone = False

    def validate_query_runner_access(self, user: "User") -> bool:
        from posthog.rbac.user_access_control import UserAccessControlError

        raise UserAccessControlError("tracing", "viewer")

    def _calculate(self) -> TraceSpansQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="TraceSpansQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            filters=HogQLFilters(dateRange=self.query.dateRange),
            settings=self.settings,
        )
        results = []
        for result in response.results:
            results.append(
                {
                    "uuid": result[0],
                    "trace_id": result[1],
                    "span_id": result[2],
                    "parent_span_id": result[3],
                    "name": result[4],
                    "kind": result[5],
                    "service_name": result[6],
                    "status_code": result[7],
                    "timestamp": result[8].replace(tzinfo=ZoneInfo("UTC")),
                    "end_time": result[9].replace(tzinfo=ZoneInfo("UTC")),
                    "duration_nano": result[10],
                }
            )

        return TraceSpansQueryResponse(results=results, **self.paginator.response_params())

    def run(self, *args, **kwargs) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
        return response

    def to_query(self) -> ast.SelectQuery:
        order_dir = "ASC" if self.query.orderBy == "earliest" else "DESC"

        query = self.paginator.paginate(
            parse_select(
                """
            SELECT
                uuid,
                hex(tryBase64Decode(trace_id)),
                hex(tryBase64Decode(span_id)),
                hex(tryBase64Decode(parent_span_id)),
                name,
                kind,
                service_name,
                status_code,
                timestamp,
                end_time,
                duration_nano
            FROM posthog.trace_spans
            WHERE {where}
        """,
                placeholders={
                    "where": self.where(),
                },
            )
        )
        assert isinstance(query, ast.SelectQuery)
        query.order_by = [
            parse_order_expr(f"end_time {order_dir}"),
            parse_order_expr(f"uuid {order_dir}"),
        ]
        return query

    def where(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        exprs.append(
            parse_expr(
                "toStartOfDay(time_bucket) >= toStartOfDay({date_from}) and toStartOfDay(time_bucket) <= toStartOfDay({date_to})",
                placeholders={
                    **self.query_date_range.to_placeholders(),
                },
            )
        )

        exprs.append(ast.Placeholder(expr=ast.Field(chain=["filters"])))

        if self.query.rootSpans:
            exprs.append(
                parse_expr(
                    "is_root_span = true",
                )
            )

        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        if self.query.statusCodes:
            exprs.append(
                parse_expr(
                    "status_code IN {statusCodes}",
                    placeholders={
                        "statusCodes": ast.Tuple(exprs=[ast.Constant(value=int(sc)) for sc in self.query.statusCodes])
                    },
                )
            )

        if self.query.searchTerm:
            exprs.append(
                parse_expr(
                    "name ILIKE {searchTerm}",
                    placeholders={
                        "searchTerm": ast.Constant(value=f"%{self.query.searchTerm}%"),
                    },
                )
            )

        if self.query.traceId:
            exprs.append(
                parse_expr(
                    "trace_id = base64Encode(unhex({traceId}))",
                    placeholders={
                        "traceId": ast.Constant(value=self.query.traceId),
                    },
                )
            )

        if self.query.after:
            try:
                cursor = json.loads(base64.b64decode(self.query.after).decode("utf-8"))
                cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
                cursor_uuid = cursor["uuid"]
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                raise ValueError(f"Invalid cursor format: {e}")

            op = ">" if self.query.orderBy == "earliest" else "<"
            ts_op = ">=" if self.query.orderBy == "earliest" else "<="

            exprs.append(
                parse_expr(
                    f"time_bucket {ts_op} toStartOfDay({{cursor_ts}})",
                    placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
                )
            )
            exprs.append(
                parse_expr(
                    f"timestamp {ts_op} {{cursor_ts}}",
                    placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
                )
            )
            exprs.append(
                parse_expr(
                    f"(timestamp, uuid) {op} ({{cursor_ts}}, {{cursor_uuid}})",
                    placeholders={
                        "cursor_ts": ast.Constant(value=cursor_ts),
                        "cursor_uuid": ast.Constant(value=cursor_uuid),
                    },
                )
            )

        return ast.And(exprs=exprs)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=2,
            now=dt.datetime.now(),
        )

    @cached_property
    def settings(self):
        return HogQLGlobalSettings(
            allow_experimental_object_type=False,
            allow_experimental_join_condition=False,
            transform_null_in=False,
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )
