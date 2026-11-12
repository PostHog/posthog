import json
import contextvars
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property, partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.db import connections

import posthoganalytics

from posthog.schema import (
    CachedMCPDashboardQueryResponse,
    CacheMissResponse,
    DateRange,
    HogQLFilters,
    MCPDashboardQuery,
    MCPDashboardQueryResponse,
    MCPDashboardSection,
    MCPDashboardSectionResult,
    QueryStatusResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.api_queries_budget import (
    QueryCost,
    get_request_query_cost,
    record_request_query_cost,
    reset_request_query_cost,
)
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.exceptions import ClickHouseAtCapacity
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.hogql_queries.utils.parallel import run_in_parallel_threads
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.instance_setting import get_instance_setting

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.mcp_analytics.backend.custom_harnesses import custom_harness_rules
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
    from posthog.event_usage import AnalyticsProps
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
LEAN_DATABASE_FLAG = "mcp-analytics-dashboard-lean-database"


def public_error(error: Exception) -> str:
    if isinstance(error, ExposedHogQLError | ExposedCHQueryError | UserAccessControlError):
        return str(error)
    return GENERIC_SECTION_ERROR


COMPARISON_SECTIONS = frozenset(section for section, hogql in HOGQL_SECTIONS.items() if hogql.spans_comparison_window)

# Each section caches itself, so these are the only modes that change what a section of a batch does.
SECTION_EXECUTION_MODES = {ExecutionMode.CALCULATE_BLOCKING_ALWAYS, ExecutionMode.CACHE_ONLY_NEVER_CALCULATE}
ASYNC_EXECUTION_MODES = {
    ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
    ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
    ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
}
CAPACITY_ERRORS = (ClickHouseAtCapacity, ConcurrencyLimitExceeded)


@dataclass(frozen=True)
class SectionRun:
    section: MCPDashboardSection
    outcome: CachedMCPDashboardQueryResponse | CacheMissResponse | Exception
    # Recorded in the section's own context, so the batch adds it to the request's cost.
    cost: QueryCost | None
    stale: bool = False

    @property
    def result(self) -> MCPDashboardSectionResult:
        if isinstance(self.outcome, Exception):
            # The section's run already captured what is worth capturing.
            return MCPDashboardSectionResult(error=public_error(self.outcome))
        assert isinstance(self.outcome, CachedMCPDashboardQueryResponse)
        return self.outcome.results[self.section.value]


class MCPDashboardQueryRunner(HarnessLabelQueryRunner[MCPDashboardQueryResponse]):
    """Every section of the MCP Analytics dashboard, each from a query the server owns.

    A query for one section computes it. A query for several runs each section as its own one-section
    query, concurrently, and caches nothing of its own: each section keeps its own cache entry, freshness,
    single flight, failure breaker and concurrency slots, and a section that fails leaves the others intact.
    """

    query: MCPDashboardQuery
    cached_response: CachedMCPDashboardQueryResponse
    _batch: Optional["MCPDashboardQueryRunner"] = None

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

    @property
    def shared_database(self) -> Database:
        # A batch's sections build the database once between them, and only when one misses the cache.
        return self._batch.shared_database if self._batch else super().shared_database

    def _on_user_changed(self) -> None:
        self.__dict__.pop("_lean_database", None)
        super()._on_user_changed()

    def _create_database(self, *, timings: HogQLTimings | None = None, trigger: str) -> Database:
        if not self._lean_database:
            return super()._create_database(timings=timings, trigger=trigger)
        return Database.create_for_posthog_tables(
            self.team,
            modifiers=self.modifiers,
            timings=timings,
            group_types=get_group_types_for_project(self.team.project_id),
            mcp_custom_harness_rules=custom_harness_rules(self.team),
        )

    @cached_property
    def _lean_database(self) -> bool:
        # A batch's sections share one database across threads, so batches keep the full build.
        if self._is_batch or self._batch is not None:
            return False
        return self._filters_fit_lean_database() and self._lean_database_flag_enabled()

    def _filters_fit_lean_database(self) -> bool:
        filters = [prop.model_dump() for prop in self.query.properties or []]
        if self.query.filterTestAccounts:
            filters += self.team.test_account_filters or []
        # Any other filter can reach tables the lean database lacks, such as the warehouse views behind `$virt_revenue`.
        return all(
            prop.get("type") in {"event", "person"} and not str(prop.get("key", "")).startswith("$virt_")
            for prop in filters
        )

    def _lean_database_flag_enabled(self) -> bool:
        distinct_id = (self.user and self.user.distinct_id) or str(self.team.uuid)
        try:
            return bool(
                posthoganalytics.feature_enabled(
                    LEAN_DATABASE_FLAG,
                    distinct_id,
                    groups={"organization": str(self.team.organization_id), "project": str(self.team.uuid)},
                    person_properties={"email": self.user.email} if self.user else None,
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
        except Exception:
            return False

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise NotImplementedError("The dashboard is many queries, not one.")

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        # A relative range moves the comparison window every minute. Only the sections that read it key on it,
        # so the others keep their entries across page loads.
        if COMPARISON_SECTIONS.isdisjoint(self._sections):
            payload["query"].pop("comparison")
        # Keeps rows built on the lean database apart, so turning the flag off never serves them.
        if self._lean_database:
            payload["lean_database"] = True
        return payload

    @cached_property
    def _sections(self) -> list[MCPDashboardSection]:
        return list(dict.fromkeys(self.query.sections))

    @cached_property
    def _is_batch(self) -> bool:
        return len(self._sections) > 1

    def run(
        self,
        execution_mode: ExecutionMode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        user: Optional["User"] = None,
        query_id: Optional[str] = None,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
        cache_age_seconds: Optional[int] = None,
        analytics_props: Optional["AnalyticsProps"] = None,
    ) -> CachedMCPDashboardQueryResponse | CacheMissResponse | QueryStatusResponse:
        # An async job reruns the batch with a forced refresh, which reaches every section.
        if not self._is_batch or execution_mode == ExecutionMode.CALCULATE_ASYNC_ALWAYS:
            return super().run(
                execution_mode=execution_mode,
                user=user,
                query_id=query_id,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
                cache_age_seconds=cache_age_seconds,
                analytics_props=analytics_props,
            )
        if user is not None:
            self.set_user(user)
            if not user.is_anonymous:
                self.validate_query_runner_access(user)
        self.query_id = query_id or self.query_id
        self.validate()

        if execution_mode in ASYNC_EXECUTION_MODES:
            runs = self._run_sections(
                ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                cache_age_seconds=cache_age_seconds,
                dashboard_id=dashboard_id,
                lazy=execution_mode == ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
            )
            all_cached = all(isinstance(run.outcome, CachedMCPDashboardQueryResponse) for run in runs)
            if all_cached and not any(run.stale for run in runs):
                return self._batch_response(runs)
            if all_cached or execution_mode != ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS:
                # One job computes every section, and the caller polls it as it would any async query.
                return super().run(
                    execution_mode=ExecutionMode.CALCULATE_ASYNC_ALWAYS,
                    user=user,
                    query_id=query_id,
                    insight_id=insight_id,
                    dashboard_id=dashboard_id,
                    cache_age_seconds=cache_age_seconds,
                    analytics_props=analytics_props,
                )

        if execution_mode not in SECTION_EXECUTION_MODES:
            execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        runs = self._run_sections(execution_mode, cache_age_seconds=cache_age_seconds, dashboard_id=dashboard_id)
        if execution_mode == ExecutionMode.CALCULATE_BLOCKING_ALWAYS:
            # The async job computes the batch this way. Failing it on overload lets the job retry with backoff.
            for run in runs:
                if isinstance(run.outcome, CAPACITY_ERRORS):
                    raise run.outcome
        if any(isinstance(run.outcome, CacheMissResponse) for run in runs):
            return CacheMissResponse(cache_key=self.get_cache_key())
        return self._batch_response(runs)

    def _batch_response(self, runs: list[SectionRun]) -> CachedMCPDashboardQueryResponse:
        computed = [run.outcome for run in runs if isinstance(run.outcome, CachedMCPDashboardQueryResponse)]
        now = datetime.now(UTC)
        target_ages = [response.cache_target_age for response in computed if response.cache_target_age]
        return CachedMCPDashboardQueryResponse(
            results={run.section.value: run.result for run in runs},
            is_cached=len(computed) == len(runs) and all(response.is_cached for response in computed),
            # The oldest section dates the batch, so a client never reads it as fresher than its stalest data.
            last_refresh=min((response.last_refresh for response in computed), default=now),
            next_allowed_client_refresh=min(
                (response.next_allowed_client_refresh for response in computed), default=now
            ),
            cache_target_age=min(target_ages, default=None),
            cache_key=self.get_cache_key(),
            timezone=self.team.timezone,
            modifiers=self.modifiers,
        )

    def _calculate(self) -> MCPDashboardQueryResponse:
        if self._is_batch:
            runs = self._run_sections(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE, cache_age_seconds=None)
            return MCPDashboardQueryResponse(
                results={run.section.value: run.result for run in runs}, modifiers=self.modifiers
            )
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

    def _run_sections(
        self,
        execution_mode: ExecutionMode,
        *,
        cache_age_seconds: Optional[int],
        dashboard_id: Optional[int] = None,
        lazy: bool = False,
    ) -> list[SectionRun]:
        run_section = partial(
            self._run_section,
            execution_mode=execution_mode,
            cache_age_seconds=cache_age_seconds,
            dashboard_id=dashboard_id,
            lazy=lazy,
        )
        runs: dict[MCPDashboardSection, SectionRun] = {}
        if settings.IN_UNIT_TESTING:
            # Django does not make the test transaction visible to another thread. Each section still runs in
            # its own copy of the context, as it does in a thread.
            for section in self._sections:
                runs[section] = contextvars.copy_context().run(run_section, section)
        else:

            def run_in_thread(section: MCPDashboardSection) -> None:
                try:
                    runs[section] = run_section(section)
                finally:
                    # Django's request cleanup never reaches a worker thread's connections, on any alias.
                    connections.close_all()

            run_in_parallel_threads(
                [partial(run_in_thread, section) for section in self._sections], thread_name_prefix="mcp_dashboard"
            )

        for run in runs.values():
            if run.cost is not None:
                record_request_query_cost(run.cost)
        return [runs[section] for section in self._sections]

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
        runner._batch = self
        return runner

    def _run_section(
        self,
        section: MCPDashboardSection,
        *,
        execution_mode: ExecutionMode,
        cache_age_seconds: Optional[int],
        dashboard_id: Optional[int],
        lazy: bool,
    ) -> SectionRun:
        # The context is a copy of the request's, so it starts with the cost of whatever ran before.
        reset_request_query_cost()
        outcome: CachedMCPDashboardQueryResponse | CacheMissResponse | Exception
        stale = False
        try:
            runner = self._section_runner(section)
            response = runner.run(
                execution_mode=execution_mode,
                user=self.user,
                dashboard_id=dashboard_id,
                cache_age_seconds=cache_age_seconds,
            )
            assert isinstance(response, CachedMCPDashboardQueryResponse | CacheMissResponse)
            outcome = response
            if isinstance(response, CachedMCPDashboardQueryResponse):
                stale = runner._is_stale_for_request(response.last_refresh, lazy=lazy)
        except Exception as error:
            outcome = error
        return SectionRun(section=section, outcome=outcome, cost=get_request_query_cost(), stale=stale)

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
        if runner.modifiers == self.modifiers and get_instance_setting("HOGQL_SHARED_INSIGHT_DATABASE_ENABLED"):
            runner._shared_database = self.shared_database
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
            context=self.build_hogql_context(),
        )
        if response.error:
            raise QueryError(response.error)
        return response.results
