import datetime as dt
import json
from zoneinfo import ZoneInfo

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.parser import parse_select, parse_expr, parse_order_expr
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    CachedLogsQueryResponse,
    HogQLFilters,
    LogsQuery,
    LogsQueryResponse,
    IntervalType,
    PropertyGroupsMode,
    PropertyOperator,
    LogPropertyFilter,
)


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

        def get_property_type(value):
            try:
                value = float(value)
                return "float"
            except ValueError:
                pass
            # todo: datetime?
            return "str"

        if len(self.query.filterGroup.values) > 0:
            filter_keys = []
            # dynamically detect type of the given property values
            # if they all convert cleanly to float, use the __float property mapping instead
            # we keep multiple attribute maps for different types:
            # attribute_map_str
            # attribute_map_float
            # attribute_map_datetime
            #
            # for now we'll just check str and float as we need a decent UI for datetime filtering.
            for property_filter in self.query.filterGroup.values[0].values:
                if isinstance(property_filter, LogPropertyFilter) and property_filter.value:
                    property_type = "str"
                    if isinstance(property_filter.value, list):
                        property_types = {get_property_type(v) for v in property_filter.value}
                        # only use the detected type if all given values have the same type
                        # e.g. if values are '1', '2', we can use float, if values are '1', 'a', stick to str
                        if len(property_types) == 1:
                            property_type = property_types.pop()
                    else:
                        property_type = get_property_type(property_filter.value)
                    property_filter.key += f"__{property_type}"
                    # for all operators except SET and NOT_SET we add an IS_SET operator to force
                    # the property key bloom filter index to be used.
                    if property_filter.operator not in (PropertyOperator.IS_SET, PropertyOperator.IS_NOT_SET):
                        filter_keys.append(property_filter.key)

            for filter_key in filter_keys:
                self.query.filterGroup.values[0].values.insert(
                    0,
                    LogPropertyFilter(
                        key=filter_key,
                        operator=PropertyOperator.IS_SET,
                        type="log",
                    ),
                )

    def calculate(self) -> LogsQueryResponse:
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        response = self.paginator.execute_hogql_query(
            query_type="LogsQuery",
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
                    "body": result[3],
                    "attributes": {k: json.loads(v) for k, v in result[4].items()},
                    "timestamp": result[5],
                    "observed_timestamp": result[6],
                    "severity_text": result[7],
                    "severity_number": result[8],
                    "level": result[9],
                    "resource_attributes": result[10],
                    "instrumentation_scope": result[11],
                    "event_name": result[12],
                }
            )

        return LogsQueryResponse(results=results, **self.paginator.response_params())

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
            uuid,
            hex(trace_id),
            hex(span_id),
            body,
            attributes,
            timestamp,
            observed_timestamp,
            severity_text,
            severity_number,
            level,
            resource_attributes,
            instrumentation_scope,
            event_name
            FROM logs
        """
        )
        assert isinstance(query, ast.SelectQuery)

        query.where = self.where()
        order_dir = "ASC" if self.query.orderBy == "earliest" else "DESC"
        query.order_by = [
            parse_order_expr(f"toUnixTimestamp(timestamp) {order_dir}"),
        ]

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

        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
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

        if self.query.filterGroup:
            exprs.append(property_to_expr(self.query.filterGroup, team=self.team))

        return ast.And(exprs=exprs)

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else []

    @cached_property
    def settings(self):
        return HogQLGlobalSettings(
            allow_experimental_object_type=False,
            allow_experimental_join_condition=False,
            transform_null_in=False,
        )

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

        def find_closest(target, arr):
            if not arr:
                raise ValueError("Input array cannot be empty")
            closest_number = min(arr, key=lambda x: (abs(x - target), x))

            return closest_number

        # set the number of intervals to a "round" number of minutes
        # it's hard to reason about the rate of logs on e.g. 13 minute intervals
        # the min interval is 1 minute and max interval is 1 day
        interval_count = find_closest(_step.total_seconds() // 60, [1, 2, 5, 10, 15, 30, 60, 120, 240, 360, 720, 1440])

        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=interval_type,
            interval_count=int(interval_count),
            now=dt.datetime.now(),
            timezone_info=ZoneInfo("UTC"),
        )
