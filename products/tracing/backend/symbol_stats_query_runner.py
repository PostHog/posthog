"""
Symbol-stats query runner.

Production latency for the functions in a single source file, aggregated from OpenTelemetry trace
spans that carry `code.*` source-location attributes. The client supplies the file path and the line
ranges of the symbols (functions) it cares about; the server attributes each span to the smallest
enclosing range and returns per-symbol stats (count, errors, total + p50/p95/p99 duration, and active
"busy" time where the SDK records it), each compared against the immediately-preceding equal-length
window.

Why ranges instead of grouping by line or function name:
- `code.function.name` is frequently absent in real spans, so the server can't group by function name.
- `code.line.number` may be a call site inside the body rather than the declaration line, so anchoring
  results to a single line is unreliable. A range supplied by the client's AST/LSP captures the span
  whether the SDK recorded the declaration or a call site.
- Percentiles do not compose, so they must be computed at range granularity here — the client cannot
  roll per-line percentiles up into a function.

The current and previous periods are computed in a single scan: the window is widened to span both,
and a per-span `is_current` flag drives conditional aggregates for each bucket.
"""

import math
import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedTraceSpansSymbolStatsQueryResponse,
    DateRange,
    IntervalType,
    PropertyGroupsMode,
    SourceSymbol,
    SymbolStatsGranularity,
    SymbolStatsPeriod,
    SymbolStatsRow,
    TraceSpansSymbolStatsQuery,
    TraceSpansSymbolStatsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.filters.mixins.utils import cached_property

from products.tracing.backend.logic import TIME_BUCKET_DATE_RANGE_WHERE

if TYPE_CHECKING:
    from posthog.models import Team


# OTel deprecated `code.filepath`/`code.lineno` in favor of the stable
# `code.file.path`/`code.line.number`. Spans in the wild use either generation depending on the SDK
# version, so we read the first non-empty value across both. Current names come first; if OTel renames
# again, prepend the new name here. Ref:
# https://opentelemetry.io/docs/specs/semconv/registry/attributes/code/
_CODE_FILE_PATH_KEYS = ["code.file.path", "code.filepath"]
_CODE_LINE_KEYS = ["code.line.number", "code.lineno"]

# Active span time excluding time spent awaiting children (Rust `tracing` style). Not standard OTel, so
# it is absent on most SDKs — surfaced as a parallel metric family the client uses only when present.
_BUSY_KEY = "busy_ns"

# Defensive ceiling on returned rows: one row per matched symbol (symbol mode) or per instrumented
# source line (line mode). Both are small in practice; this only guards a pathologically large file.
_MAX_RESULT_ROWS = 5000


def _str_attr_field(key: str) -> ast.Field:
    # Span attributes live in the typed str map; the property-group resolver rewrites a
    # `__str`-suffixed key into a Map read. A bare key falls through to an illegal JSON read.
    return ast.Field(chain=["attributes", f"{key}__str"])


def _first_nonempty_str_attr(keys: list[str]) -> ast.Expr:
    # Map access returns '' for a missing key (not NULL), so coalesce() can't merge generations.
    # Fold right with if(notEmpty(...)) instead, taking the first key that actually carries a value.
    expr: ast.Expr = _str_attr_field(keys[-1])
    for key in reversed(keys[:-1]):
        expr = ast.Call(
            name="if",
            args=[ast.Call(name="notEmpty", args=[_str_attr_field(key)]), _str_attr_field(key), expr],
        )
    return expr


def _normalized_file_path_expr() -> ast.Expr:
    # Recorded paths may use Windows separators; normalize to '/' so suffix matching is uniform.
    return ast.Call(
        name="replaceAll",
        args=[_first_nonempty_str_attr(_CODE_FILE_PATH_KEYS), ast.Constant(value="\\"), ast.Constant(value="/")],
    )


def _line_expr() -> ast.Expr:
    # Lines are 1-based, so a missing/unparseable line maps to 0, which falls outside every supplied
    # range (their startLine is >= 1) and is dropped by the outer `start_line > 0` filter.
    return ast.Call(name="toIntOrZero", args=[_first_nonempty_str_attr(_CODE_LINE_KEYS)])


def _range_key_expr(symbols: list[SourceSymbol]) -> ast.Expr:
    # Map each span's line to the startLine of the smallest enclosing range, testing innermost-first
    # (largest startLine first) so a closure nested inside a function wins over the function. Conditions
    # reference the precomputed `raw_line` column (not the full line expression) so the multiIf stays small
    # regardless of symbol count. Spans matching no range fall through to 0 and are dropped downstream.
    args: list[ast.Expr] = []
    for symbol in sorted(symbols, key=lambda s: s.startLine, reverse=True):
        args.append(
            parse_expr(
                "raw_line >= {start} AND raw_line <= {end}",
                placeholders={
                    "start": ast.Constant(value=symbol.startLine),
                    "end": ast.Constant(value=symbol.endLine),
                },
            )
        )
        args.append(ast.Constant(value=symbol.startLine))
    args.append(ast.Constant(value=0))
    return ast.Call(name="multiIf", args=args)


def _normalize_request_path(file_path: str) -> str:
    # The client sends a repo-relative path; strip a leading './' or '/' so the suffix match is
    # anchored on a path segment (otherwise endsWith on '/' + path would be distorted).
    path = file_path.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _num(value: object) -> float:
    # quantileIf over a partition with no matching rows yields NaN; coerce it (and None) to 0.0 so the
    # response carries clean numbers and the client keys off the count, not NaN.
    f = float(value or 0)  # type: ignore[arg-type]
    return 0.0 if math.isnan(f) else f


def _pct_change(current: float, previous: float) -> float | None:
    # Undefined when there is no prior baseline — return null rather than a fake +inf so "new this
    # period" is distinguishable from a real delta.
    if previous <= 0:
        return None
    return (current - previous) / previous * 100.0


class TraceSpansSymbolStatsQueryRunner(AnalyticsQueryRunner[TraceSpansSymbolStatsQueryResponse]):
    """Per-symbol latency stats for one source file, aggregated into client-supplied line ranges.

    Single-table ``GROUP BY`` over a window spanning the current and prior periods — no raw-span scan,
    no trace expansion, no ``GROUP BY trace_id``. One row per matched symbol, bounded by ``_MAX_RESULT_ROWS``.
    """

    query: TraceSpansSymbolStatsQuery
    cached_response: CachedTraceSpansSymbolStatsQueryResponse

    def __init__(self, query: TraceSpansSymbolStatsQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)
        # UTC-pinned date constants (matching TIME_BUCKET_DATE_RANGE_WHERE) and Map-backed attribute
        # access both depend on these modifiers.
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

    @cached_property
    def _now(self) -> dt.datetime:
        # One `now` shared by both windows so the current/previous boundary lines up exactly. UTC-aware
        # to match the runner's UTC pinning — a naive now() would shift the window by the server's offset
        # on a non-UTC host.
        return dt.datetime.now(tz=ZoneInfo("UTC"))

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            timezone_info=ZoneInfo("UTC"),
            now=self._now,
        )

    @cached_property
    def _previous_date_range(self) -> QueryPreviousPeriodDateRange:
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            timezone_info=ZoneInfo("UTC"),
            now=self._now,
        )

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # No byte ceiling. The path predicate can't use an index (suffix match on a Map attribute), so it
        # full-scans the window — but the logs cluster reads that fast (a 24h scan is single-digit seconds).
        # A 10GB read cap instead raised exception 307 (TOO_MANY_BYTES) on every window past ~1h, since one
        # hour alone reads ~6.5GB; max_execution_time is the real runaway backstop. This matches the sibling
        # attribute-breakdown runner, which scans the same data uncapped.
        return HogQLGlobalSettings(
            allow_experimental_object_type=False,
            max_execution_time=30,
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )

    def to_query(self) -> ast.SelectQuery:
        req = _normalize_request_path(self.query.filePath)

        # Segment-anchored suffix match in BOTH directions: recorded and request match when one's
        # segment list is a '/'-anchored suffix of the other's. The leading '/' anchors on a segment
        # boundary, so `internal/superuser.go` never matches `user.go`.
        #   - request is a suffix of recorded: `feature-flags/src/flags/flag_matching.rs` matched by
        #     `src/flags/flag_matching.rs` (the editor sends a shorter, repo-relative path).
        #   - recorded is a suffix of request: a monorepo editor sends the workspace-prefixed
        #     `rust/feature-flags/src/flags/flag_matching.rs` while the service recorded only
        #     `feature-flags/src/flags/flag_matching.rs`.
        # `crate-b/src/mod.rs` still does not match `crate-a/src/mod.rs` (divergent leading segments).
        req_slash = "/" + req
        path_predicate = parse_expr(
            "endsWith(concat('/', {recorded}), {req_slash}) OR endsWith({req_slash_dup}, concat('/', {recorded_dup}))",
            placeholders={
                "recorded": _normalized_file_path_expr(),
                "recorded_dup": _normalized_file_path_expr(),
                "req_slash": ast.Constant(value=req_slash),
                "req_slash_dup": ast.Constant(value=req_slash),
            },
        )

        # Scan a single window spanning both periods: [previous start, current end). The previous window
        # ends exactly where the current one begins, so a span is "current" iff timestamp >= current start.
        current_start = self.query_date_range.date_from()
        scan_lower = self._previous_date_range.date_from()
        scan_upper = self.query_date_range.date_to()
        span_placeholders: dict[str, ast.Expr] = {
            "date_from": ast.Constant(value=scan_lower),
            "date_to": ast.Constant(value=scan_upper),
        }

        # The explicit timestamp bounds below (plus the day-grain time_bucket prune) fully define the
        # scan window, so no HogQLFilters/{filters} placeholder is needed — one source of truth.
        inner_where = ast.And(
            exprs=[
                parse_expr(TIME_BUCKET_DATE_RANGE_WHERE, placeholders=span_placeholders),
                parse_expr("timestamp >= {date_from} AND timestamp < {date_to}", placeholders=span_placeholders),
                path_predicate,
            ]
        )

        # Bucket each span by the smallest enclosing symbol range when symbols are supplied, otherwise by
        # its own source line. The line value is computed once as `raw_line` in the innermost scan; the
        # bucket key references that column (so the multiIf stays small). Either way the key is aliased
        # `line` and percentiles are computed at that granularity (never composed across buckets).
        bucket_key = _range_key_expr(self.query.symbols) if self.query.symbols else ast.Field(chain=["raw_line"])

        busy_field = _str_attr_field(_BUSY_KEY)
        query = parse_select(
            """
            SELECT
                line,
                countIf(is_current) AS count,
                countIf(is_current AND status_code = 2) AS error_count,
                sumIf(duration_nano, is_current) AS sum_duration_nano,
                quantileIf(0.5)(duration_nano, is_current) AS p50_duration_nano,
                quantileIf(0.95)(duration_nano, is_current) AS p95_duration_nano,
                quantileIf(0.99)(duration_nano, is_current) AS p99_duration_nano,
                countIf(is_current AND has_busy) AS busy_count,
                quantileIf(0.5)(busy_nano, is_current AND has_busy) AS p50_busy_nano,
                quantileIf(0.95)(busy_nano, is_current AND has_busy) AS p95_busy_nano,
                quantileIf(0.99)(busy_nano, is_current AND has_busy) AS p99_busy_nano,
                countIf(NOT is_current) AS prev_count,
                countIf((NOT is_current) AND status_code = 2) AS prev_error_count,
                sumIf(duration_nano, NOT is_current) AS prev_sum_duration_nano,
                quantileIf(0.5)(duration_nano, NOT is_current) AS prev_p50_duration_nano,
                quantileIf(0.95)(duration_nano, NOT is_current) AS prev_p95_duration_nano,
                quantileIf(0.99)(duration_nano, NOT is_current) AS prev_p99_duration_nano,
                countIf((NOT is_current) AND has_busy) AS prev_busy_count,
                quantileIf(0.5)(busy_nano, (NOT is_current) AND has_busy) AS prev_p50_busy_nano,
                quantileIf(0.95)(busy_nano, (NOT is_current) AND has_busy) AS prev_p95_busy_nano,
                quantileIf(0.99)(busy_nano, (NOT is_current) AND has_busy) AS prev_p99_busy_nano
            FROM (
                SELECT
                    {bucket_key} AS line,
                    status_code,
                    duration_nano,
                    busy_nano,
                    has_busy,
                    is_current
                FROM (
                    SELECT
                        {line_expr} AS raw_line,
                        status_code,
                        duration_nano,
                        {busy_expr} AS busy_nano,
                        {has_busy_expr} AS has_busy,
                        timestamp >= {current_start} AS is_current
                    FROM posthog.trace_spans
                    WHERE {inner_where}
                )
            )
            WHERE line > 0
            GROUP BY line
            HAVING count > 0 OR prev_count > 0
            ORDER BY line ASC
            LIMIT {limit}
            """,
            placeholders={
                "bucket_key": bucket_key,
                "line_expr": _line_expr(),
                "busy_expr": ast.Call(name="toFloatOrZero", args=[busy_field]),
                # Derive presence from the parsed float, not `!= ''`: a missing Map key resolves
                # inconsistently under OPTIMIZED property groups, but toFloatOrZero('') is reliably 0.
                "has_busy_expr": parse_expr(
                    "toFloatOrZero({busy}) > 0", placeholders={"busy": _str_attr_field(_BUSY_KEY)}
                ),
                "current_start": ast.Constant(value=current_start),
                "inner_where": inner_where,
                "limit": ast.Constant(value=_MAX_RESULT_ROWS),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _calculate(self) -> TraceSpansSymbolStatsQueryResponse:
        # Symbol mode buckets by client-supplied ranges; line mode (no symbols) buckets by source line.
        granularity = SymbolStatsGranularity.SYMBOL if self.query.symbols else SymbolStatsGranularity.LINE

        # An empty path would degenerate the suffix match into "ends with '/'" — nothing to aggregate.
        if not _normalize_request_path(self.query.filePath):
            return TraceSpansSymbolStatsQueryResponse(results=[], granularity=granularity)

        response = execute_hogql_query(
            query_type=self.query.kind,
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        # In symbol mode, map each row's bucket line (== the symbol's startLine) back to the requested
        # symbol so we can echo its name/endLine. Line mode has no symbols, so these stay null.
        symbols_by_start = {symbol.startLine: symbol for symbol in (self.query.symbols or [])}
        return TraceSpansSymbolStatsQueryResponse(
            results=[self._row_from_clickhouse(row, symbols_by_start) for row in response.results],
            granularity=granularity,
        )

    def _row_from_clickhouse(self, row: list, symbols_by_start: dict[int, SourceSymbol]) -> SymbolStatsRow:
        # Unpack positionally in the SELECT's column order — an added/removed column then fails loudly
        # on arity rather than silently shifting every index.
        (
            line,
            count,
            error_count,
            sum_duration_nano,
            p50_duration_nano,
            p95_duration_nano,
            p99_duration_nano,
            busy_count,
            p50_busy_nano,
            p95_busy_nano,
            p99_busy_nano,
            prev_count,
            prev_error_count,
            prev_sum_duration_nano,
            prev_p50_duration_nano,
            prev_p95_duration_nano,
            prev_p99_duration_nano,
            prev_busy_count,
            prev_p50_busy_nano,
            prev_p95_busy_nano,
            prev_p99_busy_nano,
        ) = row

        line = int(line)
        symbol = symbols_by_start.get(line)
        symbol_name, symbol_end_line = (symbol.name, symbol.endLine) if symbol else (None, None)
        current_count = count or 0
        current_error_count = error_count or 0
        current_p50 = _num(p50_duration_nano)
        current_p95 = _num(p95_duration_nano)
        current_p99 = _num(p99_duration_nano)
        previous = SymbolStatsPeriod(
            count=prev_count or 0,
            error_count=prev_error_count or 0,
            sum_duration_nano=_num(prev_sum_duration_nano),
            p50_duration_nano=_num(prev_p50_duration_nano),
            p95_duration_nano=_num(prev_p95_duration_nano),
            p99_duration_nano=_num(prev_p99_duration_nano),
            busy_count=prev_busy_count or 0,
            p50_busy_nano=_num(prev_p50_busy_nano),
            p95_busy_nano=_num(prev_p95_busy_nano),
            p99_busy_nano=_num(prev_p99_busy_nano),
        )
        # Error rate per window (0 when the window had no traffic); the delta is null when the previous
        # window's rate is 0 — no errors or no traffic — so a 0→N spike reads as "no baseline", not +inf.
        current_error_rate = current_error_count / current_count if current_count else 0.0
        previous_error_rate = previous.error_count / previous.count if previous.count else 0.0
        return SymbolStatsRow(
            line=line,
            name=symbol_name,
            end_line=symbol_end_line,
            count=current_count,
            error_count=current_error_count,
            sum_duration_nano=_num(sum_duration_nano),
            p50_duration_nano=current_p50,
            p95_duration_nano=current_p95,
            p99_duration_nano=current_p99,
            busy_count=busy_count or 0,
            p50_busy_nano=_num(p50_busy_nano),
            p95_busy_nano=_num(p95_busy_nano),
            p99_busy_nano=_num(p99_busy_nano),
            previous=previous,
            count_pct_change=_pct_change(current_count, previous.count),
            p50_duration_pct_change=_pct_change(current_p50, previous.p50_duration_nano),
            p95_duration_pct_change=_pct_change(current_p95, previous.p95_duration_nano),
            p99_duration_pct_change=_pct_change(current_p99, previous.p99_duration_nano),
            error_rate_pct_change=_pct_change(current_error_rate, previous_error_rate),
        )

    def run(self, *args, **kwargs) -> TraceSpansSymbolStatsQueryResponse | CachedTraceSpansSymbolStatsQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansSymbolStatsQueryResponse | CachedTraceSpansSymbolStatsQueryResponse)
        return response


def run_symbol_stats_query(
    *,
    team: "Team",
    file_path: str,
    date_range: DateRange,
    symbols: list[SourceSymbol] | None = None,
) -> TraceSpansSymbolStatsQueryResponse | CachedTraceSpansSymbolStatsQueryResponse:
    """Facade-friendly entry point: per-line (no symbols) or per-symbol latency stats for one source file."""
    query = TraceSpansSymbolStatsQuery(dateRange=date_range, filePath=file_path, symbols=symbols)
    runner = TraceSpansSymbolStatsQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansSymbolStatsQueryResponse | CachedTraceSpansSymbolStatsQueryResponse)
    return response
