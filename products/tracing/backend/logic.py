"""
Business logic for tracing.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    DateRange,
    HogQLFilters,
    IntervalType,
    PropertyGroupsMode,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.rbac.user_access_control import UserAccessControl

from products.tracing.backend.constants import TRACE_SPANS_LIST_SETTINGS
from products.tracing.backend.filter_builder import TraceSpansFilterBuilder
from products.tracing.backend.query_date_range import tracing_qdr_baseline, tracing_qdr_minutely

if TYPE_CHECKING:
    from posthog.models import Team, User


class TraceSpansQueryRunnerMixin(QueryRunner):
    """Shared date range, filter builder, and settings for trace span query runners."""

    def __init__(self, query: TraceSpansQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self._filter_builder = TraceSpansFilterBuilder(self.team, self.query)

    def where(self) -> ast.Expr:
        return self._filter_builder.build_where(self.query_date_range)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        qdr = QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=2,
            now=dt.datetime.now(),
        )

        _step = (qdr.date_to() - qdr.date_from()) / 50
        interval_type = IntervalType.SECOND

        def find_closest(target: float, arr: list[int]) -> int:
            if not arr:
                raise ValueError("Input array cannot be empty")
            closest_number = min(arr, key=lambda x: (abs(x - target), x))

            return closest_number

        interval_count = find_closest(
            _step.total_seconds(),
            [1, 5, 10] + [x * 60 for x in [1, 2, 5, 10, 15, 30, 60, 120, 240, 360, 720, 1440]],
        )

        if _step >= dt.timedelta(minutes=1):
            interval_type = IntervalType.MINUTE
            interval_count //= 60

        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=interval_type,
            interval_count=int(interval_count),
            now=dt.datetime.now(),
            timezone_info=ZoneInfo("UTC"),
            exact_timerange=True,
        )

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return TRACE_SPANS_LIST_SETTINGS

    def validate_query_runner_access(self, user: "User") -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        return user_access_control.assert_access_level_for_resource("tracing", "viewer")


class TraceSpansQueryRunner(TraceSpansQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse
    paginator: HogQLHasMorePaginator

    def _calculate(self) -> TraceSpansQueryResponse:
        limit_by_n = self.query.prefetchSpans or 1
        query = self.to_query()
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit * limit_by_n if self.query.limit else None,
            offset=0,
        )

        response = self.paginator.execute_hogql_query(
            query_type="TraceSpansQuery",
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            filters=HogQLFilters(dateRange=self.query.dateRange),
            settings=self.settings,
        )
        results = []
        for result in response.results:
            row: dict = {
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
                "is_root_span": result[11],
                "matched_filter": result[12],
            }
            results.append(row)

        return TraceSpansQueryResponse(results=results, **self.paginator.response_params())

    def run(self, *args, **kwargs) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
        return response

    def to_query(self) -> ast.SelectQuery:
        order_dir = "ASC" if self.query.orderBy == "earliest" else "DESC"
        limit_by_n = self.query.prefetchSpans or 1

        trace_id_query = self.paginator.paginate(
            parse_select(
                """
            SELECT
                trace_id
            FROM posthog.trace_spans
            WHERE {where}
            LIMIT 1 by trace_id
            LIMIT {limit}
        """,
                placeholders={
                    "where": self.where(),
                    "limit": ast.Constant(value=self.query.limit),
                },
            )
        )

        assert isinstance(trace_id_query, ast.SelectQuery)
        trace_id_query.order_by = [
            parse_order_expr(f"timestamp {order_dir}"),
        ]

        query = parse_select(
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
                duration_nano,
                is_root_span,
                {where} as matched_filter
            FROM posthog.trace_spans
            WHERE {filters} AND trace_id IN ({trace_id_query}) LIMIT {limit}
        """,
            placeholders={
                "where": self.where(),
                "trace_id_query": trace_id_query,
                "limit": ast.Constant(value=(self.query.limit or 1) * limit_by_n),
                "filters": ast.Placeholder(expr=ast.Field(chain=["filters"])),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        query.order_by = [
            parse_order_expr("is_root_span DESC"),
            parse_order_expr("matched_filter DESC"),
            parse_order_expr(f"timestamp {order_dir}"),
        ]

        query.limit_by = ast.LimitByExpr(
            n=ast.Constant(value=limit_by_n),
            exprs=[ast.Field(chain=["trace_id"])],
        )

        return query


def run_service_names_query(
    team: "Team",
    date_range: DateRange,
    search: str = "",
) -> list[dict]:
    """Return distinct service names from trace spans."""
    query_date_range = tracing_qdr_minutely(team, date_range)

    exprs: list[ast.Expr] = [
        parse_expr(
            "toStartOfDay(time_bucket) >= toStartOfDay({date_from}) and toStartOfDay(time_bucket) <= toStartOfDay({date_to})",
            placeholders={**query_date_range.to_placeholders()},
        ),
        ast.Placeholder(expr=ast.Field(chain=["filters"])),
    ]

    if search:
        exprs.append(
            parse_expr(
                "service_name ILIKE {search}",
                placeholders={"search": ast.Constant(value=f"%{search}%")},
            )
        )

    where = ast.And(exprs=exprs)
    query = parse_select(
        """
        SELECT DISTINCT service_name
        FROM posthog.trace_spans
        WHERE {where}
        ORDER BY service_name ASC
        LIMIT 1000
        """,
        placeholders={"where": where},
    )

    response = execute_hogql_query(
        query_type="TracingServiceNamesQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        filters=HogQLFilters(dateRange=date_range),
        settings=HogQLGlobalSettings(
            allow_experimental_object_type=False,
            allow_experimental_join_condition=False,
            transform_null_in=False,
            max_bytes_to_read=None,
            read_overflow_mode=None,
        ),
    )

    return [{"name": row[0]} for row in response.results if row[0]]


def run_attribute_names_query(
    team: "Team",
    date_range: DateRange,
    attribute_type: str = "span",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return attribute names from trace_attributes table."""
    query_date_range = tracing_qdr_baseline(team, date_range)

    property_filter_type = (
        attribute_type if attribute_type in ("span", "span_attribute", "span_resource_attribute") else "span_attribute"
    )

    query = parse_select(
        """
        SELECT
            groupArray({limit})(attribute_key) as keys,
            count() as total_count
        FROM (
            SELECT
                attribute_key,
                sum(attribute_count)
            FROM posthog.trace_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND attribute_type = {attributeType}
            AND attribute_key LIKE {search}
            GROUP BY team_id, attribute_key
            ORDER BY sum(attribute_count) desc, attribute_key asc
            OFFSET {offset}
        )
        """,
        placeholders={
            "search": ast.Constant(value=f"%{search}%"),
            "attributeType": ast.Constant(value=attribute_type),
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
            **query_date_range.to_placeholders(),
        },
    )

    response = execute_hogql_query(
        query_type="TracingAttributeNamesQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        filters=HogQLFilters(dateRange=date_range),
        settings=HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=5_000_000_000,
        ),
    )

    results = []
    count = 0
    if isinstance(response.results, list) and len(response.results) > 0 and len(response.results[0]) > 0:
        for name in response.results[0][0]:
            results.append({"name": name, "propertyFilterType": property_filter_type})
        count = response.results[0][1] + offset

    return results, count


def run_attribute_values_query(
    team: "Team",
    date_range: DateRange,
    attribute_type: str = "span",
    attribute_key: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return attribute values for a given key from trace_attributes table."""
    query_date_range = tracing_qdr_baseline(team, date_range)

    query = parse_select(
        """
        SELECT
            groupArray({limit})(attribute_value) as values,
            count() as total_count
        FROM (
            SELECT
                attribute_value,
                sum(attribute_count)
            FROM posthog.trace_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND attribute_type = {attributeType}
            AND attribute_key = {attributeKey}
            AND attribute_value ILIKE {search}
            GROUP BY team_id, attribute_value
            ORDER BY sum(attribute_count) desc, attribute_value asc
            OFFSET {offset}
        )
        """,
        placeholders={
            "search": ast.Constant(value=f"%{search}%"),
            "attributeType": ast.Constant(value=attribute_type),
            "attributeKey": ast.Constant(value=attribute_key),
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
            **query_date_range.to_placeholders(),
        },
    )

    response = execute_hogql_query(
        query_type="TracingAttributeValuesQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        filters=HogQLFilters(dateRange=date_range),
        settings=HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=5_000_000_000,
        ),
    )

    results = []
    if isinstance(response.results, list) and len(response.results) > 0 and len(response.results[0]) > 0:
        for value in response.results[0][0]:
            results.append({"id": value, "name": value})

    return results
