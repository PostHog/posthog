import json
import base64
import datetime as dt
from typing import TYPE_CHECKING, cast
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
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.property import get_lowercase_index_hint, operator_is_negative, property_to_expr

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property

from products.logs.backend.column_expressions import canonical_key, column_to_expr

if TYPE_CHECKING:
    from posthog.models import Team, User


# Bounds the per-request fan-out of user-supplied HogQL expressions. Per-expression cost is already
# bounded by the query's max_execution_time / max_memory_usage; this just caps how many run at once.
# Enforced in the runner so every LogsQuery entry point (interactive query endpoint and the
# server-side CSV export worker) is bounded, not just the interactive one.
MAX_CUSTOM_COLUMNS = 50


LIVE_LOGS_CHECKPOINT_QUERY = parse_select(
    """
    SELECT min(partition_checkpoint) FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM logs_kafka_metrics
        GROUP BY _topic, _partition
    )
"""
)


def ilike_pattern(search: str | None) -> str:
    # Escape ILIKE wildcards so a search for "%" matches a literal percent sign, not every row.
    escaped = (search or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _trace_id_normalise_to_base64(value: str) -> str:
    """Accept either hex or base64 encoded trace_id/span_id values.

    The `trace_id` and `span_id` columns store base64-encoded bytes. Hex input (32-char for
    trace_id, 16-char for span_id) is the form users normally see in trace UIs, so we accept
    it and convert. Values that aren't valid hex are passed through as-is (assumed base64).
    """
    try:
        int(value, 16)
        return base64.b64encode(bytes.fromhex(value)).decode()
    except ValueError:
        return value


def _normalise_trace_id_filter(log_filter: LogPropertyFilter) -> None:
    """In-place: normalize trace_id/span_id filter values to base64 to match column storage."""
    if isinstance(log_filter.value, list):
        log_filter.value = [_trace_id_normalise_to_base64(str(v)) for v in log_filter.value]
    elif log_filter.value is not None:
        log_filter.value = _trace_id_normalise_to_base64(str(log_filter.value))


def _severity_level_to_expr(log_filter: LogPropertyFilter) -> ast.Expr:
    """Translate a `severity_level` log property filter to a HogQL expression on `severity_text`.

    Only equality operators (Exact/IsNot) are exposed in the UI.
    """
    values: list[str]
    if isinstance(log_filter.value, list):
        values = [str(v) for v in log_filter.value]
    elif log_filter.value is None:
        values = []
    else:
        values = [str(log_filter.value)]

    op = ast.CompareOperationOp.NotIn if log_filter.operator == PropertyOperator.IS_NOT else ast.CompareOperationOp.In
    return ast.CompareOperation(
        op=op,
        left=ast.Field(chain=["severity_text"]),
        right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values]),
    )


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
    # For positive filters we want resources that match ALL filters (arrayAll), then keep them via IN.
    # For negative filters we want to exclude resources that match ANY of the inverted filters
    # (arrayExists), then drop them via NOT IN — otherwise multiple negatives would only exclude
    # resources that match every one of them, instead of any one of them.
    array_fn = "arrayExists" if is_negative_filter else "arrayAll"

    # this query fetches all resource fingerprints that match at least one resource attribute filter
    # then does a secondary filter for those that match every filter (positive) or any filter (negative)
    # this sounds over complicated but it's because each row in the table is a single attribute - so we need to first group
    # them to collapse the rows into a single row per resource fingerprint, _then_ check the per-filter match counts
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
            HAVING {array_fn}(x -> x > 0, sumForEach({{ops}}))
        )
    """,
        placeholders={
            **query_date_range.to_placeholders(),
            "existing_filters": ast.And(exprs=existing_filters),
            "resource_attribute_filters": ast.Or(exprs=converted_exprs),
            "ops": ast.Array(exprs=converted_exprs),
        },
    )


def _get_property_type(value) -> str:
    try:
        float(value)
        return "float"
    except ValueError:
        pass
    # todo: datetime?
    return "str"


class LogsFilterBuilder:
    """Builds HogQL WHERE clause AST from LogsQuery filter fields.

    Standalone — no QueryRunner dependency.
    """

    def __init__(
        self,
        query: LogsQuery,
        team: "Team",
        query_date_range: QueryDateRange,
        exclude_facet_field: str | None = None,
        exclude_resource_attribute: str | None = None,
    ):
        self.query = query
        self.team = team
        self.query_date_range = query_date_range
        # When set (e.g. "severity_text" or "service_name"), that facet's own filter is omitted
        # from the WHERE clause so facet counts reflect every *other* active filter — the standard
        # faceted-search behaviour where selecting a value doesn't zero out its siblings.
        self.exclude_facet_field = exclude_facet_field
        # The resource-attribute equivalent: when faceting on a resource attribute key, omit that
        # key's own log_resource_attribute filter so the facet doesn't zero out its own siblings.
        self.exclude_resource_attribute = exclude_resource_attribute

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
                        and not operator_is_negative(f.operator)  # type: ignore[arg-type, union-attr]
                    ],
                )
                self.resource_attribute_negative_filters = cast(
                    list[LogPropertyFilter],
                    [
                        f
                        for f in property_group.values
                        if f.type == LogPropertyFilterType.LOG_RESOURCE_ATTRIBUTE and operator_is_negative(f.operator)  # type: ignore[arg-type, union-attr]
                    ],
                )
                self.log_filters = cast(
                    list[LogPropertyFilter],
                    [f for f in property_group.values if f.type == LogPropertyFilterType.LOG],
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
                        property_types = {_get_property_type(v) for v in property_filter.value}
                        # only use the detected type if all given values have the same type
                        # e.g. if values are '1', '2', we can use float, if values are '1', 'a', stick to str
                        if len(property_types) == 1:
                            property_type = property_types.pop()
                    else:
                        property_type = _get_property_type(property_filter.value)

                    # defensive copy as we mutate the filter here and don't want to impact other copies
                    property_filter = property_filter.copy(deep=True)
                    property_filter.key = f"{property_filter.key}__{property_type}"

                    self.attribute_filters.insert(0, property_filter)

        if self.exclude_resource_attribute is not None:
            self.resource_attribute_filters = [
                f for f in self.resource_attribute_filters if f.key != self.exclude_resource_attribute
            ]
            self.resource_attribute_negative_filters = [
                f for f in self.resource_attribute_negative_filters if f.key != self.exclude_resource_attribute
            ]

    def where(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        # add time_bucket to filter so we get part+granule pruning at the primary key level
        # this is important as it reduces the parts/granules that need to have their skip indexes loaded
        exprs.append(
            parse_expr(
                "toStartOfDay(time_bucket) >= toStartOfDay({date_from}) and toStartOfDay(time_bucket) <= toStartOfDay({date_to})",
                placeholders={
                    **self.query_date_range.to_placeholders(),
                },
            )
        )

        if self.query.serviceNames and self.exclude_facet_field != "service_name":
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        if self.query.resourceFingerprint:
            exprs.append(
                parse_expr(
                    "resource_fingerprint = {resourceFingerprint}",
                    placeholders={"resourceFingerprint": ast.Constant(value=str(self.query.resourceFingerprint))},
                )
            )

        if self.query.filterGroup:
            exprs.append(self.resource_filter(existing_filters=exprs))

            if self.attribute_filters:
                exprs.append(property_to_expr(self.attribute_filters, team=self.team))

            if self.log_filters:
                for log_filter in self.log_filters:
                    if log_filter.key == "severity_level":
                        if self.exclude_facet_field != "severity_text":
                            exprs.append(_severity_level_to_expr(log_filter))
                        continue
                    if log_filter.key in ("trace_id", "span_id"):
                        log_filter = log_filter.copy(deep=True)
                        _normalise_trace_id_filter(log_filter)
                    if log_filter.key == "message":
                        exprs.append(get_lowercase_index_hint(log_filter, team=self.team))
                    exprs.append(property_to_expr(log_filter, team=self.team))

        exprs.append(ast.Placeholder(expr=ast.Field(chain=["filters"])))

        if self.query.searchTerm:
            search_filter = LogPropertyFilter(
                key="body",
                operator=PropertyOperator.ICONTAINS,
                type=LogPropertyFilterType.LOG,
                value=self.query.searchTerm,
            )
            exprs.append(get_lowercase_index_hint(search_filter, team=self.team))
            exprs.append(property_to_expr(search_filter, team=self.team))

        if self.query.severityLevels and self.exclude_facet_field != "severity_text":
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
            try:
                checkpoint = dt.datetime.fromisoformat(self.query.liveLogsCheckpoint)
            except ValueError as e:
                raise ValueError(f"Invalid liveLogsCheckpoint format: {e}")
            if checkpoint.tzinfo is None:
                checkpoint = checkpoint.replace(tzinfo=ZoneInfo("UTC"))
            exprs.append(
                parse_expr(
                    "observed_timestamp >= {liveLogsCheckpoint}",
                    placeholders={"liveLogsCheckpoint": ast.Constant(value=checkpoint)},
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


class LogsQueryRunnerMixin(QueryRunner):
    # Target bucket count for the adaptive interval picker in `query_date_range`.
    # Subclasses can override per-instance to request a different resolution.
    BUCKET_TARGET: int = 50

    @cached_property
    def settings(self):
        return HogQLGlobalSettings(
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )

    def __init__(self, query, *args, **kwargs):
        super().__init__(query, *args, **kwargs)

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

    @cached_property
    def _filter_builder(self) -> LogsFilterBuilder:
        return LogsFilterBuilder(self.query, self.team, self.query_date_range)

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        qdr = QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            interval_count=2,
            now=dt.datetime.now(),
        )

        _step = (qdr.date_to() - qdr.date_from()) / self.BUCKET_TARGET
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
            exact_timerange=True,
        )

    def where(self) -> ast.Expr:
        return self._filter_builder.where()

    def resource_filter(self, *, existing_filters):
        return self._filter_builder.resource_filter(existing_filters=existing_filters)


# Number of fixed SELECT columns in to_query; custom columns are appended after these,
# so _calculate maps result[_FIXED_COLUMN_COUNT:] onto the custom column aliases.
_FIXED_COLUMN_COUNT = 15


class LogsQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    query: LogsQuery
    cached_response: CachedLogsQueryResponse
    paginator: HogQLHasMorePaginator

    def validate_query_runner_access(self, user: "User") -> bool:
        # LogsQuery is registered in get_query_runner solely for server-side CSV export.
        # The export runs via ExportedAsset + Celery and attributes the read to the export
        # owner (LimitContext.EXPORT), which must be allowed through. Block everything else —
        # i.e. user-initiated queries via the generic /api/projects/:id/query/ endpoint —
        # until the LogsQuery schema is stable and ready to be a public API.
        if self.limit_context == LimitContext.EXPORT:
            return True

        from posthog.rbac.user_access_control import UserAccessControlError

        raise UserAccessControlError("logs", "viewer")

    @cached_property
    def _custom_column_aliases(self) -> list[str]:
        return [canonical_key(text) for text in self.query.customColumns or []]

    def _custom_column_selects(self) -> list[ast.Expr]:
        custom_columns = self.query.customColumns or []
        if len(custom_columns) > MAX_CUSTOM_COLUMNS:
            raise QueryError(f"Too many custom columns: {len(custom_columns)} (max {MAX_CUSTOM_COLUMNS})")
        selects: list[ast.Expr] = []
        for text, alias in zip(custom_columns, self._custom_column_aliases):
            try:
                expr = column_to_expr(text)
            except (ValueError, ExposedHogQLError) as e:
                raise QueryError(f"Invalid custom column {text!r}: {e}")
            selects.append(ast.Alias(alias=alias, expr=expr))
        return selects

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
                    **dict(zip(self._custom_column_aliases, result[_FIXED_COLUMN_COUNT:])),
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
                    "resource_fingerprint": str(result[11]),
                    "instrumentation_scope": result[12],
                    "event_name": result[13],
                    # ClickHouse returns naive datetimes; tag as UTC like timestamp/observed_timestamp
                    # so the schema's AwareDatetime serializes with an offset rather than as a naive
                    # string the frontend would misparse in non-UTC timezones.
                    "live_logs_checkpoint": result[14].replace(tzinfo=ZoneInfo("UTC")) if result[14] else None,
                }
            )

        return LogsQueryResponse(
            results=results,
            columns=self._custom_column_aliases or None,
            **self.paginator.response_params(),
        )

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
                hex(tryBase64Decode(trace_id)),
                hex(tryBase64Decode(span_id)),
                body,
                {attributes},
                timestamp,
                observed_timestamp,
                severity_text,
                severity_number,
                severity_text as level,
                {resource_attributes},
                resource_fingerprint,
                instrumentation_scope,
                event_name,
                {live_logs_checkpoint} as live_logs_checkpoint
            FROM logs
            WHERE {where}
        """,
                placeholders={
                    "where": self.where(),
                    "live_logs_checkpoint": LIVE_LOGS_CHECKPOINT_QUERY,
                    # Attribute maps dominate payload size. When excluded we still SELECT a column
                    # (an empty map) so the positional result mapping in _calculate stays stable.
                    "attributes": parse_expr("map() AS attributes" if self.query.excludeAttributes else "attributes"),
                    "resource_attributes": parse_expr(
                        "map() AS resource_attributes" if self.query.excludeAttributes else "resource_attributes"
                    ),
                },
            )
        )
        assert isinstance(query, ast.SelectQuery)
        query.select.extend(self._custom_column_selects())
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
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )
