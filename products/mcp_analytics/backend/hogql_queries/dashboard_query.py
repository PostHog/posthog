import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property, partial
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.db import connection

from posthog.schema import (
    CachedMCPDashboardQueryResponse,
    DateRange,
    HogQLFilters,
    MCPDashboardQuery,
    MCPDashboardQueryResponse,
    MCPDashboardSection,
    MCPDashboardSectionResult,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.warehouse_warnings import detached_accumulator_scope

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode, QueryRun
from posthog.hogql_queries.utils.parallel import run_in_parallel_threads
from posthog.query_cache import QueryCache
from posthog.query_cache.single_flight import QuerySingleFlight

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.mcp_analytics.backend.hogql_queries.base import (
    EFFECTIVE_TOOL_SQL,
    HarnessLabelQueryRunner,
    validate_mcp_analytics_access,
)
from products.mcp_analytics.backend.hogql_queries.dashboard_series import (
    MCPToolCallBreakdownQueryRunner,
    MCPToolCallsAndErrorsQueryRunner,
)
from products.mcp_analytics.backend.hogql_queries.harness_breakdown import MCPHarnessBreakdownQueryRunner
from products.mcp_analytics.backend.hogql_queries.model_breakdown import MCPModelBreakdownQueryRunner
from products.mcp_analytics.backend.hogql_queries.protocol_version_breakdown import (
    MCPProtocolVersionBreakdownQueryRunner,
)

if TYPE_CHECKING:
    from posthog.models.user import User

LAB_PATTERNS: list[tuple[str, str]] = [
    (entry["lab"], entry["pattern"])
    for entry in json.loads((Path(__file__).parents[2] / "shared" / "ai_labs.json").read_text())
]

# Key on the canonical event only. Also matching the legacy `mcp_tool_call` alias would double-count.
KPI_SQL = """
SELECT
    {bucket} AS bucket,
    countDistinctIf($session_id, $session_id != '') AS sessions,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY bucket
ORDER BY bucket
"""

# Split at the bucket the selected period starts in, like the KPI tiles' bucket split, so the two agree.
# Users are counted by distinct_id, not person_id. HogQL resolves person_id through a join over every
# person override of the project, and on large projects that join runs out of memory.
PERIOD_TOTALS_SQL = """
SELECT
    uniqIf(distinct_id, timestamp >= {current_start}) AS current_users,
    uniqIf(distinct_id, timestamp < {current_start}) AS prior_users,
    round(quantileIf(0.95)(toFloat(properties.$mcp_duration_ms), timestamp >= {current_start})) AS current_p95,
    round(quantileIf(0.95)(toFloat(properties.$mcp_duration_ms), timestamp < {current_start})) AS prior_p95
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
"""

SESSION_ROWS_SQL = """
SELECT
    $session_id AS session_id,
    count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    uniq(toString(properties.$mcp_tool_name)) AS distinct_tools,
    max(timestamp) AS last_seen
FROM events
WHERE event = '$mcp_tool_call'
    AND $session_id != ''
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY session_id
HAVING tool_calls >= 1
ORDER BY tool_calls DESC
LIMIT 500
"""

TOOL_ROWS_SQL = """
SELECT
    toString(properties.$mcp_tool_name) AS tool,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_duration_ms
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY tool
ORDER BY total_calls DESC
LIMIT 50
"""

TOOL_CALL_WHERE = """event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}"""

BUCKETED_FACET_SQL = f"""
SELECT {{bucket}} AS bucket, {{label}} AS label, count() AS calls
FROM events
WHERE {TOOL_CALL_WHERE}
GROUP BY bucket, label
ORDER BY bucket
LIMIT 10000
"""

WINDOW_FACET_SQL = f"""
SELECT
    {{label}} AS label,
    count() AS calls,
    uniq(distinct_id) AS users,
    countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events
WHERE {TOOL_CALL_WHERE}
    AND {{error_filter}}
GROUP BY label
ORDER BY calls DESC
LIMIT 1000
"""

LAB_USERS_SQL = f"""
SELECT {{lab}} AS lab, uniq(distinct_id) AS users
FROM events
WHERE {TOOL_CALL_WHERE}
GROUP BY lab
"""

NAMED_MODEL_USERS_SQL = f"""
SELECT uniqIf(distinct_id, {{model}} != 'Unknown') AS users
FROM events
WHERE {TOOL_CALL_WHERE}
"""

RELIABILITY_SQL = f"""
SELECT
    {{bucket}} AS bucket,
    count() AS calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events
WHERE {TOOL_CALL_WHERE}
GROUP BY bucket
ORDER BY bucket
LIMIT 10000
"""

# toString() is load-bearing: a bare dateTrunc returns a DateTime that the API serializes with the
# project's UTC offset, which the client reads back as an instant and shifts off its wall-clock bucket keys.
BUCKET_SQL = "toString(dateTrunc({interval}, timestamp))"


def label_of(value_sql: str) -> str:
    return f"coalesce(nullIf(trim({value_sql}), ''), 'Unknown')"


MODEL_LABEL_SQL = label_of("toString(properties.$mcp_llm_model)")
# The protocol version can be inferred as a DateTime property, so read the raw string like
# MCPProtocolVersionBreakdownQueryRunner does.
PROTOCOL_VERSION_LABEL_SQL = label_of("JSONExtractString(properties, '$mcp_protocol_version')")
TOOL_LABEL_SQL = label_of(EFFECTIVE_TOOL_SQL)
ERROR_TYPE_LABEL_SQL = label_of("toString(properties.$mcp_error_type)")


def lab_expr() -> ast.Expr:
    """The lab a model belongs to: the first pattern in shared/ai_labs.json that matches, as the client's modelLab."""
    args: list[ast.Expr] = [
        parse_expr("{model} = 'Unknown'", placeholders={"model": parse_expr(MODEL_LABEL_SQL)}),
        ast.Constant(value="Unknown"),
    ]
    for lab, pattern in LAB_PATTERNS:
        lowered_model = ast.Call(name="lower", args=[parse_expr(MODEL_LABEL_SQL)])
        args += [ast.Call(name="match", args=[lowered_model, ast.Constant(value=pattern)]), ast.Constant(value=lab)]
    return ast.Call(name="multiIf", args=[*args, ast.Constant(value="Other")])


@dataclass(frozen=True)
class HogQLSection:
    sql: str
    # Placeholders that do not depend on the request. Built per run so that two queries never share an AST node.
    expressions: Mapping[str, Callable[[], ast.Expr]] = field(default_factory=dict)
    # The KPI tiles read the selected period and the one before it in one query.
    spans_comparison_window: bool = False


def _bucketed_facet(label_sql: str) -> HogQLSection:
    return HogQLSection(BUCKETED_FACET_SQL, {"label": partial(parse_expr, label_sql)})


def _window_facet(label_sql: str, error_filter_sql: str = "true") -> HogQLSection:
    return HogQLSection(
        WINDOW_FACET_SQL,
        {"label": partial(parse_expr, label_sql), "error_filter": partial(parse_expr, error_filter_sql)},
    )


HOGQL_SECTIONS: dict[MCPDashboardSection, HogQLSection] = {
    MCPDashboardSection.KPIS: HogQLSection(KPI_SQL, spans_comparison_window=True),
    MCPDashboardSection.PERIOD_TOTALS: HogQLSection(PERIOD_TOTALS_SQL, spans_comparison_window=True),
    MCPDashboardSection.TOOL_ROWS: HogQLSection(TOOL_ROWS_SQL),
    MCPDashboardSection.SESSION_ROWS: HogQLSection(SESSION_ROWS_SQL),
    MCPDashboardSection.MODEL: _bucketed_facet(MODEL_LABEL_SQL),
    MCPDashboardSection.PROTOCOL_VERSION: _bucketed_facet(PROTOCOL_VERSION_LABEL_SQL),
    MCPDashboardSection.TOOL: _window_facet(TOOL_LABEL_SQL),
    MCPDashboardSection.ERROR_TYPE: _window_facet(ERROR_TYPE_LABEL_SQL, "toBool(properties.$mcp_is_error)"),
    MCPDashboardSection.LAB_USERS: HogQLSection(LAB_USERS_SQL, {"lab": lab_expr}),
    MCPDashboardSection.NAMED_MODEL_USERS: HogQLSection(
        NAMED_MODEL_USERS_SQL, {"model": partial(parse_expr, MODEL_LABEL_SQL)}
    ),
    MCPDashboardSection.RELIABILITY: HogQLSection(RELIABILITY_SQL),
}


@dataclass(frozen=True)
class TypedSection:
    runner: type[AnalyticsQueryRunner]
    bucketed: bool = False


TYPED_SECTIONS: dict[MCPDashboardSection, TypedSection] = {
    MCPDashboardSection.HARNESS_ROWS: TypedSection(MCPHarnessBreakdownQueryRunner),
    MCPDashboardSection.MODEL_ROWS: TypedSection(MCPModelBreakdownQueryRunner),
    MCPDashboardSection.PROTOCOL_VERSION_ROWS: TypedSection(MCPProtocolVersionBreakdownQueryRunner),
    MCPDashboardSection.ACTIVITY_ROWS: TypedSection(MCPToolCallsAndErrorsQueryRunner, bucketed=True),
    MCPDashboardSection.TOOL_DAILY_ROWS: TypedSection(MCPToolCallBreakdownQueryRunner, bucketed=True),
}

GENERIC_SECTION_ERROR = "This section could not be loaded."


def public_error(error: Exception) -> str:
    if isinstance(error, ExposedHogQLError | ExposedCHQueryError | UserAccessControlError):
        return str(error)
    return GENERIC_SECTION_ERROR


class MCPDashboardQueryRunner(HarnessLabelQueryRunner[MCPDashboardQueryResponse]):
    """Every section of the MCP Analytics dashboard, each from a query the server owns.

    A query for one section computes it. A query for several runs each section as its own one-section
    query, concurrently, so each section keeps its own cache entry, single flight, failure breaker and
    concurrency slots, and a section that fails leaves the others intact.
    """

    query: MCPDashboardQuery
    cached_response: CachedMCPDashboardQueryResponse
    _refresh_sections = False

    def validate(self) -> None:
        super().validate()
        comparison = self.query.comparison
        try:
            date_from = datetime.fromisoformat(comparison.dateFrom)
            datetime.strptime(comparison.currentStartBucket, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise QueryError("The comparison window needs an ISO 8601 dateFrom and a YYYY-MM-DD HH:mm:ss bucket.")
        if date_from.tzinfo is None:
            raise QueryError("The comparison window's dateFrom needs a UTC offset.")

    def validate_query_runner_access(self, user: "User") -> bool:
        return validate_mcp_analytics_access(self.team, user)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise NotImplementedError("The dashboard is many queries, not one.")

    @cached_property
    def _sections(self) -> list[MCPDashboardSection]:
        return list(dict.fromkeys(self.query.sections))

    @cached_property
    def _is_batch(self) -> bool:
        return len(self._sections) > 1

    def _joins_single_flight(self) -> bool:
        # QueryRunner serves a follower only the entry its leader stored. A batch with a failed section
        # stores nothing, so a batch follower would get an error in place of the sections that worked.
        # Each section joins its own flight instead.
        return not self._is_batch and super()._joins_single_flight()

    def _call_with_rate_limits(self, *, dashboard_id: Optional[int]) -> tuple[MCPDashboardQueryResponse, float]:
        if not self._is_batch:
            return super()._call_with_rate_limits(dashboard_id=dashboard_id)
        # QueryRunner takes the concurrency slots, budget check and chargeable tag here. Each section's own
        # run() takes them, so a batch that held a slot too would count the request twice, and with one
        # free organization slot it would hold that slot while every section waits for another.
        start = perf_counter()
        response = self.calculate()
        return response, round((perf_counter() - start) * 1000, 2)

    def _calculate_and_cache_blocking(
        self, *, query_run: QueryRun, cache_manager: QueryCache, flight: QuerySingleFlight | None = None
    ) -> CachedMCPDashboardQueryResponse:
        # The execution mode reaches this seam but not _calculate. A forced refresh must reach the
        # sections, or it would rebuild the batch around their cached rows.
        self._refresh_sections = query_run.execution_mode == ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        return super()._calculate_and_cache_blocking(query_run=query_run, cache_manager=cache_manager, flight=flight)

    def _calculate(self) -> MCPDashboardQueryResponse:
        if not self._is_batch:
            section = self._sections[0]
            with tags_context(
                product=Product.MCP_ANALYTICS,
                feature=Feature.QUERY,
                team_id=self.team.id,
                name=f"mcp_dashboard_{section.value}",
            ):
                rows = self._section_rows(section)
            return MCPDashboardQueryResponse(
                results={section.value: MCPDashboardSectionResult(results=rows)}, modifiers=self.modifiers
            )

        results: dict[MCPDashboardSection, MCPDashboardSectionResult] = {}
        if settings.IN_UNIT_TESTING:
            # Django does not make the test transaction visible to another thread.
            results = {section: self._section_result(section) for section in self._sections}
        else:

            def run_in_thread(section: MCPDashboardSection) -> None:
                try:
                    results[section] = self._section_result(section)
                finally:
                    connection.close()

            run_in_parallel_threads(
                [partial(run_in_thread, section) for section in self._sections], thread_name_prefix="mcp_dashboard"
            )

        failed = [section.value for section in self._sections if results[section].error is not None]
        return MCPDashboardQueryResponse(
            results={section.value: results[section] for section in self._sections},
            # QueryRunner never caches a response with an error, so a partly failed batch does not hide
            # its failed sections until the entry expires.
            error=f"Sections failed: {', '.join(failed)}" if failed else None,
            modifiers=self.modifiers,
        )

    def _section_runner(self, section: MCPDashboardSection) -> "MCPDashboardQueryRunner":
        runner = MCPDashboardQueryRunner(
            query=self.query.model_copy(update={"sections": [section]}),
            team=self.team,
            user=self.user,
            limit_context=self.limit_context,
            # Concurrency slots are keyed by query id, so sections sharing one would share one slot.
            query_id=f"{self.query_id}:{section.value}" if self.query_id else None,
            workload=self.workload,
            ch_user=self.ch_user,
        )
        runner.is_query_service = self.is_query_service
        return runner

    def _section_result(self, section: MCPDashboardSection) -> MCPDashboardSectionResult:
        execution_mode = (
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS
            if self._refresh_sections
            else ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        )
        try:
            # Each section caches its own response, so it must not carry the warnings of sections run before it.
            with detached_accumulator_scope():
                response = self._section_runner(section).run(
                    execution_mode=execution_mode, user=self.user, cache_age_seconds=self._cache_age_override
                )
            assert isinstance(response, CachedMCPDashboardQueryResponse)
            return response.results[section.value]
        except Exception as error:
            # The section's run already captured what is worth capturing.
            return MCPDashboardSectionResult(error=public_error(error))

    def _section_rows(self, section: MCPDashboardSection) -> Any:
        if typed := TYPED_SECTIONS.get(section):
            return self._typed_rows(typed)
        return self._hogql_rows(section, HOGQL_SECTIONS[section])

    def _typed_rows(self, typed: TypedSection) -> Any:
        node: dict[str, Any] = {
            "dateRange": self.query.dateRange,
            "properties": self.query.properties,
            "filterTestAccounts": self.query.filterTestAccounts,
        }
        if typed.bucketed:
            node["interval"] = self.query.interval
        runner = typed.runner(
            query=node,
            team=self.team,
            user=self.user,
            modifiers=self.modifiers,
            # The query endpoint gives HogQL the extended timeout and the typed MCP nodes the standard one,
            # and each section keeps what its standalone query got.
            limit_context=LimitContext.QUERY if self.limit_context == LimitContext.QUERY_ASYNC else self.limit_context,
            workload=self.workload,
            ch_user=self.ch_user,
        )
        return runner.calculate().results

    def _hogql_rows(self, section: MCPDashboardSection, hogql: HogQLSection) -> Any:
        date_range = (
            DateRange(date_from=self.query.comparison.dateFrom, date_to=self.query.dateRange.date_to)
            if hogql.spans_comparison_window
            else self.query.dateRange
        )
        filters = HogQLFilters(
            dateRange=date_range, properties=self.query.properties, filterTestAccounts=self.query.filterTestAccounts
        )
        interval = ast.Constant(value=self.query.interval.value)
        placeholders: dict[str, ast.Expr] = {
            "bucket": parse_expr(BUCKET_SQL, placeholders={"interval": interval}),
            "current_start": ast.Call(
                name="toDateTime",
                args=[
                    ast.Constant(value=self.query.comparison.currentStartBucket),
                    ast.Constant(value=self.team.timezone),
                ],
            ),
            **{name: build() for name, build in hogql.expressions.items()},
        }
        response = execute_hogql_query(
            query=hogql.sql,
            filters=filters,
            placeholders=placeholders,
            team=self.team,
            user=self.user,
            query_type=f"mcp_dashboard_{section.value}",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            workload=self.workload,
            ch_user=self.ch_user,
        )
        if response.error:
            raise QueryError(response.error)
        return response.results
