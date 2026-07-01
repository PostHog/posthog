"""
Business logic for tracing.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

import json
import base64
import decimal
import datetime as dt
from typing import TYPE_CHECKING, cast
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
    PropertyOperator,
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

# Value-search probes attribute_value with ILIKE %search%, which scans far more rows than
# the key-only path. Require a meaningfully specific term so short prefixes (e.g. "id")
# don't trigger an expensive scan.
MIN_VALUE_SEARCH_LENGTH = 4


def _ilike_pattern(search: str) -> str:
    # Escape ILIKE wildcards so a search for "%" matches a literal percent sign, not every row.
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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


def _normalise_kind_values(values: list) -> list[str]:
    # span.kind → string-digit codes. Accept labels ("Server"), digit strings ("2"), ints, and
    # integer-valued floats (the API value union coerces JSON numbers to float). Unrecognised
    # values are dropped — never left in a form that silently matches every row. Mirrors
    # _normalise_status_code_values so both int columns are compared as digit strings.
    normalised: list[str] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            normalised.append(str(int(v)))
        elif isinstance(v, str) and v.isdigit():
            normalised.append(v)
        elif str(v) in _SPAN_KIND_LABEL_TO_INT:
            normalised.append(str(_SPAN_KIND_LABEL_TO_INT[str(v)]))
    return normalised


def _normalise_status_code_values(values: list) -> list[str]:
    # span.status_code → string-digit codes. Accept labels ("OK"/"Error"), digit strings, ints,
    # and integer-valued floats; 'OK' expands to {0, 1}. Unrecognised values are dropped — never
    # left in a form that silently matches every row.
    normalised: list[str] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            normalised.append(str(int(v)))
        elif isinstance(v, str) and v.isdigit():
            normalised.append(v)
        elif str(v) in _STATUS_CODE_LABEL_TO_INTS:
            normalised.extend(str(code) for code in _STATUS_CODE_LABEL_TO_INTS[str(v)])
    return normalised


def translate_span_filter(span_filter: SpanPropertyFilter) -> None:
    """Translate UI/API filter values into ClickHouse column representations, in place.

    The filter UI stores human-readable forms — hex ids, seconds for duration, label
    strings for `kind`/`status_code` — but the ClickHouse columns are base64 bytes,
    nanoseconds, and integers. Every code path that turns a `SpanPropertyFilter` into
    a WHERE clause must apply this translation before calling `property_to_expr`,
    otherwise filters like `{key: "kind", value: "Server"}` silently match zero rows.

    Idempotent — safe to call repeatedly on the same filter. Compare-mode invokes
    `_where_without_date_range()` once per window on the same `SpanPropertyFilter`
    instances, so `kind`/`status_code` normalisation must accept its own already-translated
    output (ints / digit strings) and not collapse it to `[]` on the second pass.
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
                str(int(decimal.Decimal(str(v)) * 1000000)) for v in span_filter.value if _is_number(str(v))
            ]
        elif _is_number(str(span_filter.value)):
            span_filter.value = str(int(decimal.Decimal(str(span_filter.value)) * 1000000))

    if span_filter.key == "kind" and span_filter.value is not None:
        values: list = span_filter.value if isinstance(span_filter.value, list) else [span_filter.value]
        # cast bridges list invariance: helper returns list[str], value's slot is the wider union.
        span_filter.value = cast("list[str | int | float]", _normalise_kind_values(values))

    if span_filter.key == "status_code" and span_filter.value is not None:
        values = span_filter.value if isinstance(span_filter.value, list) else [span_filter.value]
        span_filter.value = cast("list[str | int | float]", _normalise_status_code_values(values))


# Operators whose semantics require numeric ordering — only these need the Float64 map. Every other
# operator (equality, substring, regex, set/unset) is correct on the universal str map.
_NUMERIC_SPAN_ATTRIBUTE_OPERATORS = frozenset(
    {
        PropertyOperator.GT,
        PropertyOperator.GTE,
        PropertyOperator.LT,
        PropertyOperator.LTE,
        PropertyOperator.BETWEEN,
        PropertyOperator.NOT_BETWEEN,
    }
)


def _is_numeric(value: object) -> bool:
    # bool is a numeric subclass in Python, but OTel booleans are stored as the strings 'true'/'false'
    # (so they live in the str map, not the float map) — keep them off the numeric path.
    if isinstance(value, bool):
        return False
    try:
        float(value)  # type: ignore[arg-type]
        return True
    except (ValueError, TypeError):
        return False


def with_span_attribute_type_suffix(prop: SpanPropertyFilter) -> SpanPropertyFilter:
    """Return a copy of a span-attribute filter whose key carries its physical-map type suffix.

    Span attributes live in typed ClickHouse Maps; the property-group resolver routes a key by its
    suffix — ``__str`` → ``attributes_map_str`` (every attribute, string values) and ``__float`` →
    ``attributes_map_float`` (only attributes whose stored value parsed numeric). A bare key matches no
    group and prints an illegal JSON read on the Map column (a 500), so a suffix is always required.

    Route by *operator*, not by the filter value's type: only numeric comparison operators need the
    float map for correct ordering, and only when their value is actually numeric. Everything else —
    equality, substring/regex, and value-less is_set/is_not_set — uses the universal str map, so
    string-stored values are never silently dropped and booleans resolve against their stored form.
    """
    suffix = "str"
    if prop.operator in _NUMERIC_SPAN_ATTRIBUTE_OPERATORS:
        values = prop.value if isinstance(prop.value, list) else [prop.value]
        if values and all(_is_numeric(v) for v in values):
            suffix = "float"

    prop = prop.model_copy(deep=True)
    prop.key = f"{prop.key}__{suffix}"
    return prop


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
                        if isinstance(prop, SpanPropertyFilter):
                            prop = with_span_attribute_type_suffix(prop)
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
        flat = self._flat_spans
        # Flat mode returns one row per matching span (no per-trace prefetch), so don't inflate the
        # page size. Grouped mode locks pagination into the trace-id subquery (outer paginator at
        # offset 0); flat mode has no subquery, so its duration-order offset rides the paginator here
        # (timestamp order keysets in the WHERE instead).
        limit_by_n = 1 if flat else (self.query.prefetchSpans or 1)
        query = self.to_query()
        # original pagination settings are locked in in the trace id subquery already
        # override limit to allow for N * limit for the trace spans
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit * limit_by_n if self.query.limit else None,
            offset=self.query.offset if flat else 0,
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
                # OTel resource attributes (who/what emitted the span: service.version, host, k8s, ...).
                "resource_attributes": result[15],
                # Per-trace duration key (max matching-span duration); the offset-pagination key for
                # the slowest/fastest sorts. Falls back to this row's own duration.
                "trace_duration": result[16] if result[16] is not None else result[10],
            }
            results.append(row)

        return TraceSpansQueryResponse(results=results, **self.paginator.response_params())

    def run(self, *args, **kwargs) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
        return response

    @property
    def _by_duration(self) -> bool:
        """Ordering by duration paginates via offset; ordering by timestamp via the time keyset."""
        return self.query.orderBy == "duration"

    @property
    def _flat_spans(self) -> bool:
        """Return the matching spans themselves (one row per span), not whole-trace groups.

        Set explicitly by the viewer's "Spans" mode. The whole-trace path groups every matching span
        by trace_id to rank traces — an unbounded, high-cardinality aggregation that exceeds
        ClickHouse's memory limit for hot child attributes (e.g. code.filepath). Flat mode skips the
        GROUP BY + window and streams matches under ORDER BY ... LIMIT instead. Distinct from
        `rootSpans` (whole-trace scoping); the single-trace waterfall never sets it.
        """
        return self.query.flatSpans is True

    def _parse_after_cursor(self, secondary_key: str = "trace_id") -> tuple[dt.datetime, str] | None:
        """Decode the opaque `after` cursor into (timestamp, secondary_id_base64).

        `secondary_key` selects the keyset tiebreaker for the previous page's boundary row: "trace_id"
        for the whole-trace list (keyed on the trace's start time) or "span_id" for the flat span list
        (keyed on the span's own timestamp). The secondary id travels as hex (the human form the rest of
        the API uses) and is re-encoded to the table's base64 storage form for comparison.
        """
        if not self.query.after:
            return None
        try:
            cursor = json.loads(base64.b64decode(self.query.after).decode("utf-8"))
            cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
            cursor_id_b64 = base64.b64encode(bytes.fromhex(cursor[secondary_key])).decode("ascii")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid cursor format: {e}")
        return cursor_ts, cursor_id_b64

    def to_query(self) -> ast.SelectQuery:
        by_duration = self._by_duration
        order_dir = "ASC" if self.query.orderDirection == "ASC" else "DESC"
        if self._flat_spans:
            return self._build_flat_spans_query(by_duration=by_duration, order_dir=order_dir)
        limit_by_n = self.query.prefetchSpans or 1

        # The list paginates by trace. We GROUP BY trace_id so the page key lands on a stable
        # per-trace value — `LIMIT 1 BY trace_id` can't paginate cleanly because a multi-span trace
        # straddling the boundary would be re-selected via its other spans. Time sorts order by each
        # trace's start time (`min(timestamp)`) and keyset on it; duration sorts order by trace
        # duration (`max(duration_nano)`) and offset-paginate (the time index can't prune a duration
        # order, so keyset would pay its cost for none of its benefit).
        sort_key_sql = "max(duration_nano)" if by_duration else "min(timestamp)"

        # rootSpans is opt-in and gated on `is True` (not truthiness): the frontend never sends it
        # (None), so its prefetch-driven waterfall is untouched. An explicit True narrows the
        # trace-selection subquery to `is_root_span = 1`, so we only pick traces whose root matches
        # the filter. The outer fetch is deliberately left unfiltered — it still prefetches every
        # span of the selected traces so the waterfall gets its children.
        root_only = self.query.rootSpans is True

        subquery_where_exprs: list[ast.Expr] = [self.where()]
        if root_only:
            subquery_where_exprs.append(parse_expr("is_root_span = 1"))

        having_expr: ast.Expr | None = None
        if not by_duration:
            cursor = self._parse_after_cursor()
            op = ">" if order_dir == "ASC" else "<"
            ts_op = ">=" if order_dir == "ASC" else "<="
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
            parse_order_expr(f"{sort_key_sql} {order_dir}"),
            parse_order_expr(f"trace_id {order_dir}"),
        ]
        if having_expr is not None:
            trace_id_query.having = having_expr
        if by_duration and self.query.offset:
            trace_id_query.offset = ast.Constant(value=self.query.offset)

        # `trace_start` / `trace_duration` are the per-trace keys the view paginates and re-sorts on.
        # They MUST aggregate over the same rows the trace-selection subquery grouped, or the keys
        # diverge from the set the subquery picked — e.g. under root_only the subquery orders traces
        # by `max(duration_nano)` over root spans, so a window over *all* spans would rank a trace by
        # a long child the subquery never considered, corrupting the order and offset page boundaries.
        # Scope the key windows to match the subquery (cursor/time bounds are deliberately excluded —
        # the key is a property of the whole trace, not of the current page).
        key_predicate: ast.Expr = self.where()
        if root_only:
            key_predicate = ast.And(exprs=[self.where(), parse_expr("is_root_span = 1")])

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
                {attributes},
                {resource_attributes},
                max(if({where_for_start}, duration_nano, NULL)) OVER (PARTITION BY trace_id) as trace_duration
            FROM posthog.trace_spans
            WHERE {filters} AND trace_id IN ({trace_id_query}) LIMIT {limit}
        """,
            placeholders={
                "where": self.where(),
                "where_for_start": key_predicate,
                "trace_id_query": trace_id_query,
                "limit": ast.Constant(value=(self.query.limit or 1) * limit_by_n),
                "filters": ast.Placeholder(expr=ast.Field(chain=["filters"])),
                # The attribute maps dominate payload size (db.statement holds multi-KB SQL;
                # process.command_args etc. bulk up the resource map). When excluded we still
                # SELECT a column so the positional result mapping stays stable — an empty map
                # instead of the real one.
                "attributes": parse_expr("map() AS attributes" if self.query.excludeAttributes else "attributes"),
                "resource_attributes": parse_expr(
                    "map() AS resource_attributes" if self.query.excludeAttributes else "resource_attributes"
                ),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        # Root rows drive the displayed list order. Time sorts order them by timestamp; duration sorts
        # by the per-trace duration window (constant within a trace, so spans of a trace stay grouped).
        base_order = [parse_order_expr("is_root_span DESC"), parse_order_expr("matched_filter DESC")]
        # The single-trace waterfall paginates *within* one trace: order its spans purely by start
        # time so the per-trace `LIMIT BY` window is the first `prefetchSpans` spans by start time,
        # and an `offset` pages through the rest (infinite scroll). The multi-trace list keeps its
        # root/matched-first grouping so a trace's root and matching spans stay visible.
        single_trace = self.query.traceId is not None
        if by_duration:
            query.order_by = [
                *base_order,
                parse_order_expr(f"trace_duration {order_dir}"),
                parse_order_expr(f"trace_id {order_dir}"),
                parse_order_expr("timestamp ASC"),
            ]
        elif single_trace:
            query.order_by = [
                parse_order_expr(f"timestamp {order_dir}"),
                parse_order_expr(f"span_id {order_dir}"),
            ]
        else:
            query.order_by = [*base_order, parse_order_expr(f"timestamp {order_dir}")]

        query.limit_by = ast.LimitByExpr(
            n=ast.Constant(value=limit_by_n),
            exprs=[ast.Field(chain=["trace_id"])],
            # Within-trace offset paging — only meaningful for the single-trace waterfall (timestamp
            # order). The paginator's own offset stays 0 in grouped mode, so these don't compound.
            offset_value=ast.Constant(value=self.query.offset) if single_trace and self.query.offset else None,
        )

        return query

    def _build_flat_spans_query(self, *, by_duration: bool, order_dir: str) -> ast.SelectQuery:
        """Flat span list: the matching spans themselves, no whole-trace expansion (see _flat_spans).

        Streams matches under ORDER BY ... LIMIT (keyset on timestamp, offset on duration) instead of a
        per-trace GROUP BY + window, so a filter on a hot child attribute stays bounded. Returns the
        same positional columns as the whole-trace query so _calculate's row mapping stays shared:
        matched_filter is a constant 1 (every returned row matched), and trace_start / trace_duration
        are the span's own timestamp / duration.
        """
        where_exprs: list[ast.Expr] = [self.where()]

        # Time order keysets on (timestamp, span_id) in the WHERE; duration order offset-paginates via
        # the paginator (see _calculate). The coarse UTC day bound lets ClickHouse prune parts first —
        # pin UTC for the same reason as the date bound in where(): the cursor constant prints UTC, so
        # an unpinned toStartOfDay would truncate on the session-tz day grid and drop same-day rows.
        if not by_duration:
            cursor = self._parse_after_cursor("span_id")
            if cursor is not None:
                cursor_ts, cursor_span_id = cursor
                row_op = ">" if order_dir == "ASC" else "<"
                day_op = ">=" if order_dir == "ASC" else "<="
                where_exprs.append(
                    parse_expr(
                        f"toStartOfDay(time_bucket, 'UTC') {day_op} toStartOfDay({{cursor_ts}}, 'UTC')",
                        placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
                    )
                )
                where_exprs.append(
                    parse_expr(
                        f"(timestamp, span_id) {row_op} ({{cursor_ts}}, {{cursor_span_id}})",
                        placeholders={
                            "cursor_ts": ast.Constant(value=cursor_ts),
                            "cursor_span_id": ast.Constant(value=cursor_span_id),
                        },
                    )
                )

        where: ast.Expr = where_exprs[0] if len(where_exprs) == 1 else ast.And(exprs=where_exprs)

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
                1 as matched_filter,
                timestamp as trace_start,
                {attributes},
                {resource_attributes},
                duration_nano as trace_duration
            FROM posthog.trace_spans
            WHERE {where}
        """,
            placeholders={
                "where": where,
                "attributes": parse_expr("map() AS attributes" if self.query.excludeAttributes else "attributes"),
                "resource_attributes": parse_expr(
                    "map() AS resource_attributes" if self.query.excludeAttributes else "resource_attributes"
                ),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        # span_id is the per-span tiebreaker (base64 storage form, matching the cursor) — keeps the
        # ORDER BY and the keyset WHERE on the same representation so pagination is stable.
        sort_col = "duration_nano" if by_duration else "timestamp"
        query.order_by = [
            parse_order_expr(f"{sort_col} {order_dir}"),
            parse_order_expr(f"span_id {order_dir}"),
        ]
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
                placeholders={"search": ast.Constant(value=_ilike_pattern(search))},
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
    search_values: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return attribute names from trace_attributes table.

    When search_values is set and the search term is specific enough, also match
    on attribute values so a user can find the key holding e.g. a trace_id.
    """
    if search_values and search and len(search) >= MIN_VALUE_SEARCH_LENGTH:
        return _run_attribute_names_value_search(
            team=team,
            date_range=date_range,
            attribute_type=attribute_type,
            search=search,
            limit=limit,
            offset=offset,
        )

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
            AND attribute_key ILIKE {search}
            GROUP BY team_id, attribute_key
            ORDER BY sum(attribute_count) desc, attribute_key asc
            OFFSET {offset}
        )
        """,
        placeholders={
            "search": ast.Constant(value=_ilike_pattern(search)),
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
            results.append({"name": name, "propertyFilterType": property_filter_type, "matchedOn": "key"})
        count = response.results[0][1] + offset

    return results, count


def _run_attribute_names_value_search(
    team: "Team",
    date_range: DateRange,
    attribute_type: str,
    search: str,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    # UNION ALL of two branches:
    #   (1) keys whose name matches the search
    #   (2) keys whose values match the search but whose name does NOT match
    # The NOT-ILIKE on the value branch dedupes — a key never appears twice.
    # match_type lets the outer ORDER BY put key matches above value matches.
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
            attribute_key,
            match_type,
            sample_value,
            total_count
        FROM (
            SELECT
                attribute_key,
                'key' AS match_type,
                '' AS sample_value,
                sum(attribute_count) AS total_count
            FROM posthog.trace_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND attribute_type = {attributeType}
            AND attribute_key ILIKE {search}
            GROUP BY team_id, attribute_key

            UNION ALL

            SELECT
                attribute_key,
                'value' AS match_type,
                argMax(attribute_value, attribute_count) AS sample_value,
                sum(attribute_count) AS total_count
            FROM posthog.trace_attributes
            WHERE time_bucket >= {date_from_start_of_interval}
            AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
            AND attribute_type = {attributeType}
            AND attribute_value ILIKE {search}
            AND attribute_key NOT ILIKE {search}
            GROUP BY team_id, attribute_key
        )
        ORDER BY
            match_type = 'key' DESC,
            total_count DESC,
            attribute_key ASC
        LIMIT {limit}
        OFFSET {offset}
        """,
        placeholders={
            "search": ast.Constant(value=_ilike_pattern(search)),
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
    if isinstance(response.results, list):
        for row in response.results:
            attribute_key, match_type, sample_value, _total_count = row
            matched_on_key = match_type == "key"
            results.append(
                {
                    "name": attribute_key,
                    "propertyFilterType": property_filter_type,
                    "matchedOn": "key" if matched_on_key else "value",
                    "matchedValue": None if matched_on_key else (sample_value or None),
                }
            )

    # Total count for value-search isn't separately computed; use the returned page
    # size plus offset as a lower bound — enough for the "load more" affordance.
    return results, len(results) + offset


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
            "search": ast.Constant(value=_ilike_pattern(search)),
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


def run_aggregation_query(
    *,
    team: "Team",
    date_range: DateRange,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
    """Facade-friendly entry point for running a flat span aggregation query."""
    # The runners import `translate_span_filter` from this module, so a module-level import here is circular.
    from .aggregation_query_runner import TraceSpansAggregationQueryRunner  # noqa: PLC0415

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
    # Same circular import as run_aggregation_query above.
    from .aggregation_query_runner import TraceSpansTreeQueryRunner  # noqa: PLC0415

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
