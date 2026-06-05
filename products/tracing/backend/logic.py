"""
Business logic for tracing.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

import json
import base64
import decimal
import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedTraceSpansAggregationQueryResponse,
    CachedTraceSpansQueryResponse,
    CachedTraceSpansTreeQueryResponse,
    CompareFilter,
    DateRange,
    HogQLFilters,
    HogQLQueryModifiers,
    IntervalType,
    PropertyGroupFilter,
    PropertyGroupsMode,
    SpanPropertyFilter,
    SpanPropertyFilterType,
    TraceSpansAggregationQuery,
    TraceSpansAggregationQueryResponse,
    TraceSpansQuery,
    TraceSpansQueryResponse,
    TraceSpansTreeQuery,
    TraceSpansTreeQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode, QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property

if TYPE_CHECKING:
    from posthog.models import Team, User


# Day-range bound on time_bucket, pinned to UTC. With convertToProjectTimezone=False the date
# constants print UTC-pinned, while bare DateTime columns read in the session tz; pinning both
# sides keeps them on the same day grid so a non-UTC session can't drop same-day rows (which
# previously emptied keyset page 2).
TIME_BUCKET_DATE_RANGE_WHERE = (
    "toStartOfDay(time_bucket, 'UTC') >= toStartOfDay({date_from}, 'UTC') "
    "and toStartOfDay(time_bucket, 'UTC') <= toStartOfDay({date_to}, 'UTC')"
)


def _normalise_to_base64(value: str) -> str:
    try:
        int(value, 16)
        return base64.b64encode(bytes.fromhex(value)).decode()
    except ValueError:
        return value


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


# OTel span.kind enum labels sent from the filter UI, mapped to their wire integer values.
_SPAN_KIND_LABEL_TO_INT: dict[str, int] = {
    "Unspecified": 0,
    "Internal": 1,
    "Server": 2,
    "Client": 3,
    "Producer": 4,
    "Consumer": 5,
}

# OTel status_code label → int. 'OK' expands to {0, 1} so 'unset' spans match 'ok' filters.
_STATUS_CODE_LABEL_TO_INTS: dict[str, list[int]] = {
    "OK": [0, 1],
    "Error": [2],
}


def translate_span_filter(span_filter: SpanPropertyFilter) -> None:
    """Translate UI/API filter values into ClickHouse column representations, in place.

    The filter UI stores human-readable forms — hex ids, seconds for duration, label
    strings for `kind`/`status_code` — but the ClickHouse columns are base64 bytes,
    nanoseconds, and integers. Every code path that turns a `SpanPropertyFilter` into
    a WHERE clause must apply this translation before calling `property_to_expr`,
    otherwise filters like `{key: "kind", value: "Server"}` silently match zero rows.

    Idempotent — safe to call repeatedly on the same filter. Compare-mode invokes
    `_where_without_date_range()` once per window on the same `SpanPropertyFilter`
    instances; without the post-translation guards on `kind`/`status_code` the second
    pass would map the already-translated integers back to `[]` and silently drop the
    filter for the compare window.
    """
    if span_filter.key in ("trace_id", "span_id"):
        # `_normalise_to_base64` is a no-op on already-base64 values (16/8-byte ids
        # always encode to padding-suffixed strings that fail `int(_, 16)`).
        if isinstance(span_filter.value, list):
            span_filter.value = [_normalise_to_base64(str(v)) for v in span_filter.value]
        else:
            span_filter.value = _normalise_to_base64(str(span_filter.value))

    if span_filter.key == "duration":
        # Key flips to `duration_nano` after first pass, so this block is unreachable
        # on subsequent invocations.
        span_filter.key = "duration_nano"
        if isinstance(span_filter.value, list):
            span_filter.value = [
                str(decimal.Decimal(str(v)) * 1000000) for v in span_filter.value if _is_number(str(v))
            ]
        elif _is_number(str(span_filter.value)):
            span_filter.value = str(decimal.Decimal(str(span_filter.value)) * 1000000)

    if span_filter.key == "kind" and span_filter.value is not None:
        values: list = span_filter.value if isinstance(span_filter.value, list) else [span_filter.value]
        if not all(isinstance(v, int) for v in values):
            span_filter.value = [_SPAN_KIND_LABEL_TO_INT[str(v)] for v in values if str(v) in _SPAN_KIND_LABEL_TO_INT]

    if span_filter.key == "status_code" and span_filter.value is not None:
        values = span_filter.value if isinstance(span_filter.value, list) else [span_filter.value]
        if not all(isinstance(v, str) and v.isdigit() for v in values):
            expanded: list[int] = []
            for v in values:
                if str(v) in _STATUS_CODE_LABEL_TO_INTS:
                    expanded.extend(_STATUS_CODE_LABEL_TO_INTS[str(v)])
            span_filter.value = [str(v) for v in expanded]


class TraceSpansQueryRunnerMixin(QueryRunner):
    """Shared WHERE clause and settings for all trace span query runners."""

    def __init__(self, query: TraceSpansQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

        def get_property_type(value: str | float | bool) -> str:
            try:
                float(value)
                return "float"
            except (ValueError, TypeError):
                pass
            return "str"

        self.span_filters: list[SpanPropertyFilter] = []
        self.span_attribute_filters: list[SpanPropertyFilter] = []
        self.resource_attribute_filters: list[SpanPropertyFilter] = []
        if self.query.filterGroup and self.query.filterGroup.values:
            for property_group in self.query.filterGroup.values:
                for prop in property_group.values:
                    prop_type = getattr(prop, "type", None)
                    if prop_type == SpanPropertyFilterType.SPAN_RESOURCE_ATTRIBUTE:
                        self.resource_attribute_filters.append(prop)
                    if prop_type == SpanPropertyFilterType.SPAN:
                        self.span_filters.append(prop)
                    elif prop_type == SpanPropertyFilterType.SPAN_ATTRIBUTE:
                        if isinstance(prop, SpanPropertyFilter) and prop.value:
                            property_type = "str"
                            if isinstance(prop.value, list):
                                property_types = {get_property_type(v) for v in prop.value}
                                if len(property_types) == 1:
                                    property_type = property_types.pop()
                            else:
                                property_type = get_property_type(prop.value)

                            prop = prop.model_copy(deep=True)
                            prop.key = f"{prop.key}__{property_type}"

                        self.span_attribute_filters.append(prop)

    def where(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        exprs.append(
            parse_expr(
                TIME_BUCKET_DATE_RANGE_WHERE,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                },
            )
        )

        exprs.append(ast.Placeholder(expr=ast.Field(chain=["filters"])))

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

        if self.span_filters:
            for span_filter in self.span_filters:
                translate_span_filter(span_filter)
                exprs.append(property_to_expr(span_filter, team=self.team))

        if self.span_attribute_filters:
            exprs.append(property_to_expr(self.span_attribute_filters, team=self.team))

        if self.resource_attribute_filters:
            for f in self.resource_attribute_filters:
                exprs.append(property_to_expr(f, team=self.team))

        if self.query.traceId:
            trace_id_b64 = base64.b64encode(bytes.fromhex(self.query.traceId)).decode("ascii")
            exprs.append(
                parse_expr(
                    "trace_id = {traceId}",
                    placeholders={
                        "traceId": ast.Constant(value=trace_id_b64),
                    },
                )
            )

        # Note: the `after` cursor is intentionally NOT applied here. The list paginates at the
        # trace level (see `TraceSpansQueryRunner.to_query`), so a span-level keyset would wrongly
        # filter child spans of the kept traces. The shared where() is also used by the sparkline,
        # aggregation and tree runners, which never paginate.

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

        _step = (qdr.date_to() - qdr.date_from()) / 50
        interval_type = IntervalType.SECOND

        def find_closest(target: float, arr: list[int]) -> int:
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

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            allow_experimental_object_type=False,
            allow_experimental_join_condition=False,
            transform_null_in=False,
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )


class TraceSpansQueryRunner(TraceSpansQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse
    paginator: HogQLHasMorePaginator

    def validate_query_runner_access(self, user: "User") -> bool:
        from posthog.rbac.user_access_control import UserAccessControlError

        raise UserAccessControlError("tracing", "viewer")

    def _calculate(self) -> TraceSpansQueryResponse:
        limit_by_n = self.query.prefetchSpans or 1
        query = self.to_query()
        # original pagination settings are locked in in the trace id subquery already
        # override limit to allow for N * limit for the trace spans
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
                # Per-trace pagination key (earliest matching-span timestamp); identical for every
                # span of a trace. Falls back to this row's timestamp on the off chance it is null.
                "trace_start": (result[13] or result[8]).replace(tzinfo=ZoneInfo("UTC")),
                # OTel span attributes the user set, as a key-value map.
                "attributes": result[14],
            }
            results.append(row)

        return TraceSpansQueryResponse(results=results, **self.paginator.response_params())

    def run(self, *args, **kwargs) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
        return response

    def _parse_after_cursor(self) -> tuple[dt.datetime, str] | None:
        """Decode the opaque `after` cursor into (trace_start_ts, trace_id_base64).

        The cursor identifies the last trace of the previous page by its start time (the root
        span's timestamp) and trace id. `trace_id` travels as hex (the human form the rest of the
        API uses) and is re-encoded to the table's base64 storage form for comparison.
        """
        if not self.query.after:
            return None
        try:
            cursor = json.loads(base64.b64decode(self.query.after).decode("utf-8"))
            cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
            cursor_trace_id_b64 = base64.b64encode(bytes.fromhex(cursor["trace_id"])).decode("ascii")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid cursor format: {e}")
        return cursor_ts, cursor_trace_id_b64

    def to_query(self) -> ast.SelectQuery:
        order_dir = "ASC" if self.query.orderBy == "earliest" else "DESC"
        limit_by_n = self.query.prefetchSpans or 1

        # The list paginates by trace, ordered by each trace's start time (its earliest span, i.e.
        # the root). We GROUP BY trace_id so the keyset cursor lands on a stable per-trace key —
        # `LIMIT 1 BY trace_id` can't keyset cleanly because a multi-span trace straddling the
        # cursor would be re-selected via its other spans.
        cursor = self._parse_after_cursor()
        op = ">" if self.query.orderBy == "earliest" else "<"
        ts_op = ">=" if self.query.orderBy == "earliest" else "<="

        # rootSpans is opt-in and gated on `is True` (not truthiness): the frontend never sends it
        # (None), so its prefetch-driven waterfall is untouched. An explicit True narrows the result
        # to root spans only — applied to both the trace-selection subquery (so we pick traces whose
        # root matches the filter) and the outer fetch (so only those roots come back), keeping
        # matched_filter consistent instead of surfacing roots flagged 0.
        root_only = self.query.rootSpans is True

        subquery_where_exprs: list[ast.Expr] = [self.where()]
        if root_only:
            subquery_where_exprs.append(parse_expr("is_root_span = 1"))
        having_expr: ast.Expr | None = None
        if cursor is not None:
            cursor_ts, cursor_trace_id = cursor
            # Coarse day bound on time_bucket lets ClickHouse prune parts via the primary index.
            # Pin both sides to UTC for the same reason as the where() date bound: the cursor
            # constant prints UTC-pinned, so an unpinned toStartOfDay would truncate on the
            # session-tz day grid and drop same-day rows under a non-UTC session.
            subquery_where_exprs.append(
                parse_expr(
                    f"toStartOfDay(time_bucket, 'UTC') {ts_op} toStartOfDay({{cursor_ts}}, 'UTC')",
                    placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
                )
            )
            having_expr = parse_expr(
                f"(min(timestamp), trace_id) {op} ({{cursor_ts}}, {{cursor_trace_id}})",
                placeholders={
                    "cursor_ts": ast.Constant(value=cursor_ts),
                    "cursor_trace_id": ast.Constant(value=cursor_trace_id),
                },
            )

        subquery_where = (
            subquery_where_exprs[0] if len(subquery_where_exprs) == 1 else ast.And(exprs=subquery_where_exprs)
        )

        trace_id_query = parse_select(
            """
            SELECT
                trace_id
            FROM posthog.trace_spans
            WHERE {where}
            GROUP BY trace_id
            LIMIT {limit}
        """,
            placeholders={
                "where": subquery_where,
                "limit": ast.Constant(value=self.query.limit),
            },
        )

        assert isinstance(trace_id_query, ast.SelectQuery)
        trace_id_query.order_by = [
            parse_order_expr(f"min(timestamp) {order_dir}"),
            parse_order_expr(f"trace_id {order_dir}"),
        ]
        if having_expr is not None:
            trace_id_query.having = having_expr

        # `trace_start` is the per-trace pagination key — the earliest timestamp among the spans
        # matching the filters, i.e. exactly what the subquery's `min(timestamp)` HAVING/ORDER BY
        # uses. Computing it here as a window over the (untruncated) span set lets the view read the
        # SQL key directly instead of re-deriving min() over the prefetched spans, which is wrong
        # for a trace whose earliest span isn't in the prefetched slice (e.g. a rootless trace with
        # prefetchSpans > 1 and orderBy="latest").
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
                {where} as matched_filter,
                min(if({where_for_start}, timestamp, NULL)) OVER (PARTITION BY trace_id) as trace_start,
                attributes
            FROM posthog.trace_spans
            WHERE {filters} AND {root_filter} AND trace_id IN ({trace_id_query}) LIMIT {limit}
        """,
            placeholders={
                "where": self.where(),
                "where_for_start": self.where(),
                "trace_id_query": trace_id_query,
                "limit": ast.Constant(value=(self.query.limit or 1) * limit_by_n),
                "filters": ast.Placeholder(expr=ast.Field(chain=["filters"])),
                "root_filter": parse_expr("is_root_span = 1") if root_only else ast.Constant(value=True),
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
    query_date_range = QueryDateRange(
        date_range=date_range,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=2,
        now=dt.datetime.now(),
    )

    exprs: list[ast.Expr] = [
        parse_expr(
            TIME_BUCKET_DATE_RANGE_WHERE,
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
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
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
    attribute_type: str = "span_attribute",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return attribute names from trace_attributes table."""
    query_date_range = QueryDateRange(
        date_range=date_range,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=10,
        now=dt.datetime.now(),
        timezone_info=ZoneInfo("UTC"),
    )

    property_filter_type = (
        attribute_type if attribute_type in ("span_attribute", "span_resource_attribute") else "span_attribute"
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
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
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
    attribute_type: str = "span_attribute",
    attribute_key: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return attribute values for a given key from trace_attributes table."""
    query_date_range = QueryDateRange(
        date_range=date_range,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=10,
        now=dt.datetime.now(),
        timezone_info=ZoneInfo("UTC"),
    )

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
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
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


# Imported below the helpers above (and `translate_span_filter`) because the runners
# import `translate_span_filter` from this module. Keeping this import at the bottom
# avoids a partial-load circular import.
from .aggregation_query_runner import TraceSpansAggregationQueryRunner, TraceSpansTreeQueryRunner  # noqa: E402


def run_aggregation_query(
    *,
    team: "Team",
    date_range: DateRange,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
    """Facade-friendly entry point for running a flat span aggregation query."""
    query = TraceSpansAggregationQuery(
        dateRange=date_range,
        compareFilter=compare_filter,
        filterGroup=filter_group,
        serviceNames=service_names,
    )
    runner = TraceSpansAggregationQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse)
    return response


def run_tree_query(
    *,
    team: "Team",
    date_range: DateRange,
    span_name: str,
    service_name: str,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansTreeQueryResponse | CachedTraceSpansTreeQueryResponse:
    """Facade-friendly entry point for running a span call-tree aggregation query."""
    query = TraceSpansTreeQuery(
        dateRange=date_range,
        spanName=span_name,
        serviceName=service_name,
        compareFilter=compare_filter,
        filterGroup=filter_group,
        serviceNames=service_names,
    )
    runner = TraceSpansTreeQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansTreeQueryResponse | CachedTraceSpansTreeQueryResponse)
    return response
