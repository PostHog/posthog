import json
import base64
import datetime as dt
from typing import cast
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedLogsQueryResponse,
    HogQLFilters,
    IntervalType,
    LogPropertyFilter,
    LogPropertyFilterType,
    LogsQuery,
    LogsQueryResponse,
    PropertyGroupsMode,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.property import operator_is_negative, property_to_expr

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property


def _generate_resource_attribute_filters(
    resource_attribute_filters, *, existing_filters, query_date_range, team, is_negative_filter
):
    """
    Helper to generate an expression which filters resource_fingerprints, either to resource matching
    a set of filters, or to exclude resources matching a set of filters (negative filters)

    e.g. for a positive filter:

        (resource_fingerprint) in (
            SELECT ...
            FROM log_attributes
            WHERE attribute_key = 'k8s.container.name' and attribute_value = 'nginx'
        )

        and for a negative filter:

        (resource_fingerprint) not in (
            SELECT ...
            FROM log_attributes
            WHERE attribute_key = 'k8s.container.name' and attribute_value = 'nginx'
        )
    """
    converted_exprs = []
    for filter in resource_attribute_filters:
        attribute_type = "resource" if filter.type == LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE else "log"
        if is_negative_filter:
            # invert the negative filter back to the positive equivalent
            # we invert the IN logic instead
            filter.operator = {
                PropertyOperator.IS_NOT: PropertyOperator.EXACT,
                PropertyOperator.NOT_ICONTAINS: PropertyOperator.ICONTAINS,
                PropertyOperator.NOT_REGEX: PropertyOperator.REGEX,
                PropertyOperator.IS_NOT_SET: PropertyOperator.IS_SET,
                PropertyOperator.NOT_BETWEEN: PropertyOperator.BETWEEN,
                PropertyOperator.NOT_IN: PropertyOperator.IN_,
            }.get(filter.operator, filter.operator)

        if filter.operator == PropertyOperator.IS_SET:
            converted_exprs.append(
                parse_expr(
                    "attribute_type = {attribute_type} AND attribute_key = {attribute_key}",
                    placeholders={
                        "attribute_type": ast.Constant(value=attribute_type),
                        "attribute_key": ast.Constant(value=filter.key),
                    },
                )
            )
            continue

        filter_expr = property_to_expr(filter, team=team, scope="log_resource")
        converted_expr = parse_expr(
            "attribute_type = {attribute_type} AND attribute_key = {attribute_key} AND {value_expr}",
            placeholders={
                "attribute_type": ast.Constant(value=attribute_type),
                "value_expr": filter_expr,
                "attribute_key": ast.Constant(value=filter.key),
            },
        )
        converted_exprs.append(converted_expr)

    IN_ = "NOT IN" if is_negative_filter else "IN"

    # this query fetches all resource fingerprints that match at least one resource attribute filter
    # then does a secondary filter for those that match every filter
    # this sounds over complicated but it's because each row in the table is a single attribute - so we need to first group
    # them to collapse the rows into a single row per resource fingerprint, _then_ check every filter is met
    return parse_expr(
        f"""
        (resource_fingerprint) {IN_}
        (
            SELECT
                resource_fingerprint
            FROM log_attributes
            WHERE
                time_bucket >= toStartOfInterval({{date_from}},toIntervalMinute(10))
                AND time_bucket <= toStartOfInterval({{date_to}},toIntervalMinute(10))
                AND {{resource_attribute_filters}} AND {{existing_filters}}
            GROUP BY resource_fingerprint
            HAVING arrayAll(x -> x > 0, sumForEach({{ops}}))
        )
    """,
        placeholders={
            **query_date_range.to_placeholders(),
            "existing_filters": ast.And(exprs=existing_filters),
            "resource_attribute_filters": ast.Or(exprs=converted_exprs),
            "ops": ast.Array(exprs=converted_exprs),
        },
    )


class LogsQueryRunnerMixin(QueryRunner):
    def __init__(self, query, *args, **kwargs):
        super().__init__(query, *args, **kwargs)

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

        def get_property_type(value):
            try:
                value = float(value)
                return "float"
            except ValueError:
                pass
            # todo: datetime?
            return "str"

        self.resource_attribute_filters: list[LogPropertyFilter] = []
        self.resource_attribute_negative_filters: list[LogPropertyFilter] = []
        self.log_filters: list[LogPropertyFilter] = []
        self.attribute_filters: list[LogPropertyFilter] = []
        if self.query.filterGroup and len(self.query.filterGroup.values) > 0:
            for property_group in self.query.filterGroup.values:
                self.resource_attribute_filters = cast(
                    list[LogPropertyFilter],
                    [
                        f
                        for f in property_group.values
                        if f.type == LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE
                        and not operator_is_negative(f.operator)
                    ],
                )
                self.resource_attribute_negative_filters = cast(
                    list[LogPropertyFilter],
                    [
                        f
                        for f in property_group.values
                        if f.type == LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE and operator_is_negative(f.operator)
                    ],
                )
                self.log_filters = cast(
                    list[LogPropertyFilter], [f for f in property_group.values if f.type == LogPropertyFilterType.LOG]
                )

            # dynamically detect type of the given property values
            # if they all convert cleanly to float, use the __float property mapping instead
            # we keep multiple attribute maps for different types:
            # attribute_map_str
            # attribute_map_float
            # attribute_map_datetime
            #
            # for now we'll just check str and float as we need a decent UI for datetime filtering.
            for property_filter in self.query.filterGroup.values[0].values:
                # we only do the type mapping for log attributes
                if property_filter.type != LogPropertyFilterType.LOG_ATTRIBUTE:
                    continue

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

                    # defensive copy as we mutate the filter here and don't want to impact other copies
                    property_filter = property_filter.copy(deep=True)
                    property_filter.key = f"{property_filter.key}__{property_type}"

                    self.attribute_filters.insert(0, property_filter)

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

        def find_closest(target, arr):
            if not arr:
                raise ValueError("Input array cannot be empty")
            closest_number = min(arr, key=lambda x: (abs(x - target), x))

            return closest_number

        # set the number of intervals to a "round" number of minutes
        # it's hard to reason about the rate of logs on e.g. 13 minute intervals
        # the min interval is 1 minute and max interval is 1 day
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
        )

    def where(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        if self.query.filterGroup:
            exprs.append(self.resource_filter(existing_filters=exprs))

            if self.attribute_filters:
                exprs.append(property_to_expr(self.attribute_filters, team=self.team))

            if self.log_filters:
                exprs.append(property_to_expr(self.log_filters, team=self.team))

        exprs.append(ast.Placeholder(expr=ast.Field(chain=["filters"])))

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

        if self.query.liveLogsCheckpoint:
            exprs.append(
                parse_expr(
                    "observed_timestamp >= {liveLogsCheckpoint}",
                    placeholders={"liveLogsCheckpoint": ast.Constant(value=self.query.liveLogsCheckpoint)},
                )
            )

        if self.query.after:
            try:
                cursor = json.loads(base64.b64decode(self.query.after).decode("utf-8"))
                cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
                cursor_uuid = cursor["uuid"]
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                raise ValueError(f"Invalid cursor format: {e}")
            # For ASC (earliest first): get rows where (timestamp, uuid) > cursor
            # For DESC (latest first, default): get rows where (timestamp, uuid) < cursor
            op = ">" if self.query.orderBy == "earliest" else "<"
            ts_op = ">=" if self.query.orderBy == "earliest" else "<="
            # The logs table is sorted by (team_id, time_bucket, ..., timestamp) where
            # time_bucket = toStartOfDay(timestamp). ClickHouse only prunes efficiently when
            # the WHERE clause matches the sorting key. A tuple comparison like
            # (timestamp, uuid) < (x, y) won't trigger pruning.
            # We add explicit scalar bounds on both time_bucket and timestamp to ensure
            # ClickHouse can use the primary index and skip irrelevant parts.
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
            # Tuple comparison handles the exact cursor position (same timestamp, different uuid)
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

    def resource_filter(self, *, existing_filters):
        negative_resource_filter = ast.Constant(value=True)
        # generate a query which excludes all the resources which match a negative filter
        # e.g. if you filter k8s.container.name != "nginx", this will return
        #      (resource_fingerprint) NOT IN (<query which returns resources which DO have k8s.container.name = "nginx">)
        if self.resource_attribute_negative_filters:
            negative_resource_filter = _generate_resource_attribute_filters(
                self.resource_attribute_negative_filters,
                team=self.team,
                existing_filters=existing_filters,
                query_date_range=self.query_date_range,
                is_negative_filter=True,
            )

        if self.resource_attribute_filters:
            return _generate_resource_attribute_filters(
                self.resource_attribute_filters,
                team=self.team,
                # negative resource filter is passed in here
                existing_filters=[*existing_filters, negative_resource_filter],
                query_date_range=self.query_date_range,
                is_negative_filter=False,
            )
        elif self.resource_attribute_negative_filters:
            # If we have both positive and negative filters, the negative filters are applied to the positive filter
            # query, so we don't need to add them again.
            # If we ONLY have negative filters, we have to add them to the top level query.
            return negative_resource_filter

        return ast.Constant(value=1)


class LogsQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    query: LogsQuery
    cached_response: CachedLogsQueryResponse
    paginator: HogQLHasMorePaginator

    def _calculate(self) -> LogsQueryResponse:
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
                    "attributes": result[4],
                    "timestamp": result[5].replace(tzinfo=ZoneInfo("UTC")),
                    "observed_timestamp": result[6].replace(tzinfo=ZoneInfo("UTC")),
                    "severity_text": result[7],
                    "severity_number": result[8],
                    "level": result[9],
                    "resource_attributes": result[10],
                    "instrumentation_scope": result[11],
                    "event_name": result[12],
                    "live_logs_checkpoint": result[13],
                }
            )

        return LogsQueryResponse(results=results, **self.paginator.response_params())

    def run(self, *args, **kwargs) -> LogsQueryResponse | CachedLogsQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)
        return response

    def to_query(self) -> ast.SelectQuery:
        order_dir = "ASC" if self.query.orderBy == "earliest" else "DESC"

        query = self.paginator.paginate(
            parse_select(
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
                severity_text as level,
                resource_attributes,
                instrumentation_scope,
                event_name,
                (select min(max_observed_timestamp) from logs_kafka_metrics) as live_logs_checkpoint
            FROM logs
            WHERE {where}
        """,
                placeholders={
                    "where": self.where(),
                },
            )
        )
        assert isinstance(query, ast.SelectQuery)
        query.order_by = [
            parse_order_expr(f"timestamp {order_dir}"),
            parse_order_expr(f"uuid {order_dir}"),
        ]
        return query

    @cached_property
    def properties(self):
        return self.query.filterGroup.values[0].values if self.query.filterGroup else []

    @cached_property
    def settings(self):
        return HogQLGlobalSettings(
            allow_experimental_object_type=False,
            allow_experimental_join_condition=False,
            transform_null_in=False,
            allow_experimental_analyzer=True,
        )
