import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, call, patch

from django.db import connections
from django.test import override_settings

from parameterized import parameterized
from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from posthog.schema import (
    CachedMCPDashboardQueryResponse,
    DataWarehouseSyncWarning,
    DateRange,
    EventPropertyFilter,
    HogQLFilters,
    HogQLQuery,
    IntervalType,
    MCPDashboardComparison,
    MCPDashboardQuery,
    MCPDashboardQueryResponse,
    MCPDashboardSection,
    MCPHarnessBreakdownQuery,
    MCPModelBreakdownQuery,
    MCPProtocolVersionBreakdownQuery,
    MCPToolCallBreakdownQuery,
    MCPToolCallsAndErrorsQuery,
    PersonPropertyFilter,
    PropertyOperator,
    QueryStatus,
    QueryStatusResponse,
    RevenueAnalyticsEventItem,
    RevenueCurrencyPropertyConfig,
    SessionPropertyFilter,
)

from posthog.hogql.constants import LimitContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.warehouse_warnings import record_warnings

from posthog.api_queries_budget import get_request_query_cost, reset_request_query_cost
from posthog.clickhouse.query_tagging import tag_queries, tags_context
from posthog.exceptions import ClickHouseAtCapacity
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models.instance_setting import override_instance_config
from posthog.query_cache.single_flight import QUERY_SINGLE_FLIGHT_FLAG, FlightWait, QuerySingleFlight
from posthog.query_scan.flag import QueryScanFlag, QueryScanMode

from products.mcp_analytics.backend.facade.api import invalidate_custom_harness_rules
from products.mcp_analytics.backend.hogql_queries.dashboard_query import LEAN_DATABASE_FLAG, MCPDashboardQueryRunner
from products.mcp_analytics.backend.models import MCPCustomHarness
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NOW = datetime(2026, 7, 23, 19, 0, tzinfo=UTC)
TIMEZONE = "US/Pacific"
DATE_RANGE = DateRange(date_from="-7d")
COMPARISON = MCPDashboardComparison(dateFrom="2026-07-09T07:00:00.000Z", currentStartBucket="2026-07-16 00:00:00")
PROPERTIES = [EventPropertyFilter(key="$mcp_client_name", value=["excluded-client"], operator=PropertyOperator.IS_NOT)]
DASHBOARD_RUNNER = "products.mcp_analytics.backend.hogql_queries.dashboard_query"

# The browser's queries before the server owned them, as mcpDashboardOverviewLogic.ts and
# mcpLeaderboardHomeLogic.ts built them for a day interval.
BUCKET = "toString(dateTrunc('day', timestamp))"
WHERE = """event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}"""


def label_of(value_sql: str) -> str:
    return f"coalesce(nullIf(trim({value_sql}), ''), 'Unknown')"


MODEL_LABEL = label_of("toString(properties.$mcp_llm_model)")
TOOL_LABEL = label_of("""coalesce(
    nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
    if(properties.$mcp_tool_name = 'exec' AND properties.$mcp_exec_verb = 'call',
       nullIf(nullIf(toString(properties.$mcp_exec_target_tool), ''), 'unrecognized'), NULL),
    toString(properties.$mcp_tool_name)
)""")
LAB_PATTERNS = json.loads((Path(__file__).parents[2] / "shared" / "ai_labs.json").read_text())
LAB_SQL = (
    f"multiIf({MODEL_LABEL} = 'Unknown', 'Unknown', "
    + ", ".join(f"match(lower({MODEL_LABEL}), '{p['pattern']}'), '{p['lab']}'" for p in LAB_PATTERNS)
    + ", 'Other')"
)


def bucketed_facet(label: str) -> str:
    return f"SELECT {BUCKET} AS bucket, {label} AS label, count() AS calls FROM events WHERE {WHERE} GROUP BY bucket, label ORDER BY bucket LIMIT 10000"


def window_facet(label: str, only_errors: str = "") -> str:
    return f"""SELECT {label} AS label, count() AS calls, uniq(distinct_id) AS users, countIf(toBool(properties.$mcp_is_error)) AS errors
FROM events WHERE {WHERE} {only_errors} GROUP BY label ORDER BY calls DESC LIMIT 1000"""


CURRENT_START = f"toDateTime('{COMPARISON.currentStartBucket}', '{TIMEZONE}')"

# (section, browser SQL, whether the browser read the doubled KPI window)
BROWSER_HOGQL: list[tuple[MCPDashboardSection, str, bool]] = [
    (
        MCPDashboardSection.KPIS,
        f"""SELECT {BUCKET} AS bucket, countDistinctIf($session_id, $session_id != '') AS sessions, count() AS tool_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors, round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events WHERE {WHERE} GROUP BY bucket ORDER BY bucket""",
        True,
    ),
    (
        MCPDashboardSection.PERIOD_TOTALS,
        f"""SELECT uniqIf(distinct_id, timestamp >= {CURRENT_START}) AS current_users,
    uniqIf(distinct_id, timestamp < {CURRENT_START}) AS prior_users,
    round(quantileIf(0.95)(toFloat(properties.$mcp_duration_ms), timestamp >= {CURRENT_START})) AS current_p95,
    round(quantileIf(0.95)(toFloat(properties.$mcp_duration_ms), timestamp < {CURRENT_START})) AS prior_p95
FROM events WHERE {WHERE}""",
        True,
    ),
    (
        MCPDashboardSection.TOOL_ROWS,
        f"""SELECT toString(properties.$mcp_tool_name) AS tool, count() AS total_calls, countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_duration_ms
FROM events WHERE {WHERE} GROUP BY tool ORDER BY total_calls DESC LIMIT 50""",
        False,
    ),
    (
        MCPDashboardSection.SESSION_ROWS,
        """SELECT $session_id AS session_id, count() AS tool_calls, countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    dateDiff('second', min(timestamp), max(timestamp)) AS duration_seconds,
    uniq(toString(properties.$mcp_tool_name)) AS distinct_tools, max(timestamp) AS last_seen
FROM events
WHERE event = '$mcp_tool_call' AND $session_id != '' AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != '' AND {filters}
GROUP BY session_id HAVING tool_calls >= 1 ORDER BY tool_calls DESC LIMIT 500""",
        False,
    ),
    (MCPDashboardSection.MODEL, bucketed_facet(MODEL_LABEL), False),
    (
        MCPDashboardSection.PROTOCOL_VERSION,
        bucketed_facet(label_of("JSONExtractString(properties, '$mcp_protocol_version')")),
        False,
    ),
    (MCPDashboardSection.TOOL, window_facet(TOOL_LABEL), False),
    (
        MCPDashboardSection.ERROR_TYPE,
        window_facet(label_of("toString(properties.$mcp_error_type)"), "AND toBool(properties.$mcp_is_error)"),
        False,
    ),
    (
        MCPDashboardSection.LAB_USERS,
        f"SELECT {LAB_SQL} AS lab, uniq(distinct_id) AS users FROM events WHERE {WHERE} GROUP BY lab",
        False,
    ),
    (
        MCPDashboardSection.NAMED_MODEL_USERS,
        f"SELECT uniqIf(distinct_id, {MODEL_LABEL} != 'Unknown') AS users FROM events WHERE {WHERE}",
        False,
    ),
    (
        MCPDashboardSection.RELIABILITY,
        f"""SELECT {BUCKET} AS bucket, count() AS calls, countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50, round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95
FROM events WHERE {WHERE} GROUP BY bucket ORDER BY bucket LIMIT 10000""",
        False,
    ),
]

BROWSER_TYPED: list[tuple[MCPDashboardSection, type, bool]] = [
    (MCPDashboardSection.HARNESS_ROWS, MCPHarnessBreakdownQuery, False),
    (MCPDashboardSection.MODEL_ROWS, MCPModelBreakdownQuery, False),
    (MCPDashboardSection.PROTOCOL_VERSION_ROWS, MCPProtocolVersionBreakdownQuery, False),
    (MCPDashboardSection.ACTIVITY_ROWS, MCPToolCallsAndErrorsQuery, True),
    (MCPDashboardSection.TOOL_DAILY_ROWS, MCPToolCallBreakdownQuery, True),
]


@override_settings(IN_UNIT_TESTING=True)
@time_machine.travel(NOW, tick=False)
class TestMCPDashboardQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = TIMEZONE
        self.team.test_account_filters = [{"key": "internal", "type": "event", "operator": "is_not_set"}]
        self.team.save()

    def _emit(self, days_ago: float, distinct_id: str, session_id: str, tool: str, **properties: Any) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=NOW - timedelta(days=days_ago),
            properties={"$session_id": session_id, "$mcp_tool_name": tool, **properties},
        )

    def _seed(self) -> None:
        claude = {"$mcp_llm_model": "claude-opus-4-5", "$mcp_client_name": "claude-code"}
        self._emit(
            1, "d1", "s1", "query_run", **claude, **{"$mcp_protocol_version": "2026-07-28"}, **{"$mcp_duration_ms": 120}
        )
        self._emit(
            1.1,
            "d1",
            "s1",
            "insight_create",
            **claude,
            **{"$mcp_is_error": True, "$mcp_error_type": "invalid_params", "$mcp_duration_ms": 900},
        )
        self._emit(
            2,
            "d2",
            "s2",
            "exec",
            **{
                "$mcp_exec_verb": "call",
                "$mcp_exec_target_tool": "dashboard_get",
                "$mcp_llm_model": "gpt-5-codex",
                "$mcp_client_name": "codex-mcp-client",
                "$mcp_protocol_version": "2025-11-25",
                "$mcp_duration_ms": 300,
            },
        )
        self._emit(
            3,
            "d3",
            "s3",
            "query_run",
            **{"$mcp_llm_model": "gpt-oss-120b", "$mcp_is_error": True, "$mcp_error_type": "timeout"},
        )
        self._emit(4, "d4", "s4", "query_run", **{"$mcp_llm_model": "", "$mcp_duration_ms": 75})
        self._emit(2, "d8", "", "query_run", **{"$mcp_llm_model": "composer-1"})
        self._emit(3, "d5", "s5", "query_run", **{"$mcp_llm_model": "gemini-2.5-pro", "internal": True})
        self._emit(3, "d6", "s6", "query_run", **{"$mcp_client_name": "excluded-client"})
        self._emit(2, "d9", "s9", "", **{"$mcp_llm_model": "claude-opus-4-5"})
        self._emit(10, "d7", "s7", "query_run", **{"$mcp_llm_model": "grok-4", "$mcp_duration_ms": 400})
        self._emit(
            12,
            "d1",
            "s8",
            "insight_create",
            **{"$mcp_llm_model": "claude-sonnet-4", "$mcp_is_error": True, "$mcp_error_type": "invalid_params"},
        )
        flush_persons_and_events()

    def _query(self, sections: list[MCPDashboardSection], **overrides: Any) -> MCPDashboardQuery:
        fields: dict[str, Any] = {
            "sections": sections,
            "dateRange": DATE_RANGE,
            "interval": IntervalType.DAY,
            "properties": PROPERTIES,
            "filterTestAccounts": True,
            "comparison": COMPARISON,
            **overrides,
        }
        return MCPDashboardQuery(**fields)

    def _runner(self, sections: list[MCPDashboardSection], **overrides: Any) -> MCPDashboardQueryRunner:
        return MCPDashboardQueryRunner(
            query=self._query(sections, **overrides),
            team=self.team,
            user=self.user,
            limit_context=LimitContext.QUERY_ASYNC,
        )

    def _run(
        self, sections: list[MCPDashboardSection], runner: MCPDashboardQueryRunner | None = None, **kwargs: Any
    ) -> CachedMCPDashboardQueryResponse:
        response = (runner or self._runner(sections)).run(user=self.user, **kwargs)
        assert isinstance(response, CachedMCPDashboardQueryResponse)
        return response

    def _rows(
        self, response: MCPDashboardQueryResponse | CachedMCPDashboardQueryResponse, section: MCPDashboardSection
    ) -> Any:
        result = response.results[section.value]
        assert result.error is None, result.error
        return to_jsonable_python(result.results)

    @parameterized.expand([(section.value, section, sql, kpi) for section, sql, kpi in BROWSER_HOGQL])
    def test_hogql_section_matches_the_browser_query(
        self, _name: str, section: MCPDashboardSection, sql: str, spans_comparison_window: bool
    ) -> None:
        self._seed()
        date_range = (
            DateRange(date_from=COMPARISON.dateFrom, date_to=DATE_RANGE.date_to)
            if spans_comparison_window
            else DATE_RANGE
        )
        browser = HogQLQueryRunner(
            query=HogQLQuery(
                query=sql,
                filters=HogQLFilters(dateRange=date_range, properties=PROPERTIES, filterTestAccounts=True),
            ),
            team=self.team,
            limit_context=LimitContext.QUERY_ASYNC,
        ).calculate()

        expected = to_jsonable_python(browser.results)
        assert expected, "the seed should give the section rows to compare"
        assert self._rows(self._run([section]), section) == expected

    @parameterized.expand([(section.value, section, node, bucketed) for section, node, bucketed in BROWSER_TYPED])
    def test_typed_section_matches_the_browser_query(
        self, _name: str, section: MCPDashboardSection, node: type, bucketed: bool
    ) -> None:
        self._seed()
        fields: dict[str, Any] = {"dateRange": DATE_RANGE, "properties": PROPERTIES, "filterTestAccounts": True}
        if bucketed:
            fields["interval"] = IntervalType.DAY
        browser = get_query_runner(node(**fields), self.team, user=self.user).calculate()

        expected = to_jsonable_python(browser.results)
        assert expected
        assert self._rows(self._run([section]), section) == expected

    @parameterized.expand([("run",), ("calculate",)])
    def test_a_batch_returns_each_section_as_its_own_query_would(self, entry_point: str) -> None:
        self._seed()
        sections = list(MCPDashboardSection)

        batch = self._run(sections) if entry_point == "run" else self._runner(sections).calculate()

        assert list(batch.results) == [section.value for section in sections]
        for section in sections:
            assert self._rows(batch, section) == self._rows(self._run([section]), section), section

    @parameterized.expand(
        [
            *(
                (f"{entry_point}_{name}", entry_point, sections, True)
                for entry_point in ("run", "calculate")
                for name, sections in (
                    ("hogql_section", [MCPDashboardSection.KPIS]),
                    ("typed_section", [MCPDashboardSection.HARNESS_ROWS]),
                    ("batch", list(MCPDashboardSection)),
                )
            ),
            ("unshared_typed_section", "run", [MCPDashboardSection.HARNESS_ROWS], False),
        ]
    )
    def test_a_query_builds_one_database_for_all_its_sections(
        self, _name: str, entry_point: str, sections: list[MCPDashboardSection], shared: bool
    ) -> None:
        self._seed()
        create_for = Database.create_for
        runner = self._runner(sections)

        with (
            override_instance_config("HOGQL_SHARED_INSIGHT_DATABASE_ENABLED", shared),
            patch.object(Database, "create_for", side_effect=create_for) as build,
        ):
            self._run(sections, runner) if entry_point == "run" else runner.calculate()

        assert build.call_count == 1

    def _seed_revenue(self) -> None:
        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName="purchase",
                revenueProperty="revenue",
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
            )
        ]
        self.team.revenue_analytics_config.save()
        _create_person(team_id=self.team.pk, distinct_ids=["d1"])
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="d1",
            timestamp=NOW - timedelta(days=2),
            properties={"revenue": 100},
        )

    @parameterized.expand(
        [
            ("one_section_per_request", PROPERTIES, False, False, "Acme Agent"),
            (
                "revenue_filter",
                [*PROPERTIES, PersonPropertyFilter(key="$virt_revenue", value=0, operator=PropertyOperator.GT)],
                False,
                True,
                "Claude Code",
            ),
            (
                "session_filter",
                [*PROPERTIES, SessionPropertyFilter(key="$session_duration", value=0, operator=PropertyOperator.GTE)],
                False,
                True,
                "Acme Agent",
            ),
            ("batch", PROPERTIES, True, True, "Acme Agent"),
        ]
    )
    def test_the_lean_database_flag_gives_every_section_the_same_rows(
        self, _name: str, properties: list, batch: bool, builds_full_catalog: bool, harness: str
    ) -> None:
        self._seed_revenue()
        self._seed()
        with self.captureOnCommitCallbacks(execute=True):
            MCPCustomHarness.objects.create(team=self.team, name="Acme Agent", match_pattern="codex")
            invalidate_custom_harness_rules(self.team)
        sections = list(MCPDashboardSection)

        def rows_by_section() -> dict[MCPDashboardSection, Any]:
            rows: dict[MCPDashboardSection, Any] = {}
            for request in [sections] if batch else [[section] for section in sections]:
                runner = self._runner(request, properties=properties)
                response = self._run(request, runner, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                rows |= {section: self._rows(response, section) for section in request}
            return rows

        full = rows_by_section()
        create_for = Database.create_for
        with (
            patch("posthoganalytics.feature_enabled", side_effect=lambda key, *_, **__: key == LEAN_DATABASE_FLAG),
            patch.object(Database, "create_for", side_effect=create_for) as full_catalog_build,
        ):
            lean = rows_by_section()

        assert (full_catalog_build.call_count > 0) == builds_full_catalog
        assert full[MCPDashboardSection.TOOL_ROWS], "the seed should leave rows to compare"
        assert harness in json.dumps(lean[MCPDashboardSection.HARNESS_ROWS])
        assert lean == full

    def test_the_lean_database_keeps_its_own_cache_entries(self) -> None:
        sections = [MCPDashboardSection.TOOL_ROWS]
        full_key = self._runner(sections).get_cache_key()

        with patch("posthoganalytics.feature_enabled", side_effect=lambda key, *_, **__: key == LEAN_DATABASE_FLAG):
            lean_key = self._runner(sections).get_cache_key()

        assert lean_key != full_key

    def test_a_failed_section_leaves_the_others_and_stays_uncached(self) -> None:
        self._seed()
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.KPIS, MCPDashboardSection.HARNESS_ROWS]
        original = MCPDashboardQueryRunner._section_rows

        def fail_kpis(runner: MCPDashboardQueryRunner, section: MCPDashboardSection) -> Any:
            if section == MCPDashboardSection.KPIS:
                raise QueryError("KPI query is broken")
            return original(runner, section)

        with patch.object(MCPDashboardQueryRunner, "_section_rows", autospec=True, side_effect=fail_kpis):
            first = self._run(sections)
            second = self._run(sections)

        assert first.results[MCPDashboardSection.KPIS.value].error == "KPI query is broken"
        assert self._rows(first, MCPDashboardSection.TOOL_ROWS)
        assert self._rows(first, MCPDashboardSection.HARNESS_ROWS)
        assert second.is_cached is False
        assert self._run([MCPDashboardSection.TOOL_ROWS]).is_cached is True
        assert self._run([MCPDashboardSection.KPIS]).is_cached is False

    @parameterized.expand(
        [
            ("blocking_keeps_the_other_sections", ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE, False),
            ("forced_fails_so_the_async_job_retries", ExecutionMode.CALCULATE_BLOCKING_ALWAYS, True),
        ]
    )
    def test_a_section_at_capacity(self, _name: str, execution_mode: ExecutionMode, fails: bool) -> None:
        self._seed()
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.KPIS]
        original = MCPDashboardQueryRunner._section_rows

        def overload_kpis(runner: MCPDashboardQueryRunner, section: MCPDashboardSection) -> Any:
            if section == MCPDashboardSection.KPIS:
                raise ClickHouseAtCapacity()
            return original(runner, section)

        with patch.object(MCPDashboardQueryRunner, "_section_rows", autospec=True, side_effect=overload_kpis):
            if fails:
                with self.assertRaises(ClickHouseAtCapacity):
                    self._run(sections, execution_mode=execution_mode)
                return
            response = self._run(sections, execution_mode=execution_mode)

        assert response.results[MCPDashboardSection.KPIS.value].error is not None
        assert self._rows(response, MCPDashboardSection.TOOL_ROWS)

    @parameterized.expand(
        [
            ("exposed_error_keeps_its_message", QueryError("Unknown property"), "Unknown property", 0),
            (
                "internal_error_is_generic_and_captured_once",
                RuntimeError("clickhouse host 10.0.0.1 exploded"),
                "This section could not be loaded.",
                1,
            ),
        ]
    )
    def test_a_section_error_never_leaks_internals(
        self, _name: str, boom: Exception, message: str, captures: int
    ) -> None:
        with (
            patch.object(MCPDashboardQueryRunner, "_section_rows", side_effect=boom),
            patch("posthog.hogql_queries.query_runner.capture_exception") as capture,
        ):
            response = self._run([MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.KPIS])

        assert response.results[MCPDashboardSection.TOOL_ROWS.value].error == message
        assert capture.call_count == captures * 2

    @parameterized.expand([("unknown_section", ["bogus"]), ("no_sections", [])])
    def test_a_malformed_section_list_is_rejected_when_the_query_is_parsed(self, _name: str, sections: list) -> None:
        with self.assertRaises(ValidationError):
            get_query_runner(
                {**self._query([MCPDashboardSection.KPIS]).model_dump(mode="json"), "sections": sections}, self.team
            )

    @parameterized.expand(
        [
            ("relative_date_from", {"dateFrom": "-14d"}),
            ("date_from_without_offset", {"dateFrom": "2026-07-09T07:00:00"}),
            ("date_from_with_sql", {"dateFrom": "2026-07-09') OR 1=1 --"}),
            ("bucket_with_t_separator", {"currentStartBucket": "2026-07-16T00:00:00"}),
            ("bucket_without_time", {"currentStartBucket": "2026-07-16"}),
            ("bucket_with_sql", {"currentStartBucket": "2026-07-16 00:00:00', 'UTC') OR (1"}),
        ]
    )
    def test_a_malformed_comparison_window_is_rejected(self, _name: str, change: dict[str, str]) -> None:
        comparison = COMPARISON.model_copy(update=change)
        with self.assertRaises(QueryError):
            self._runner([MCPDashboardSection.PERIOD_TOTALS], comparison=comparison).calculate()

    def test_each_section_takes_its_own_slots_budget_check_and_charge_and_the_batch_takes_none(self) -> None:
        held: list[str | None] = []
        org_slots: list[str | None] = []
        most_held = 0

        @contextmanager
        def slot(_team: Any, *, task_id: str | None = None) -> Iterator[None]:
            nonlocal most_held
            held.append(task_id)
            org_slots.append(task_id)
            most_held = max(most_held, len(held))
            yield
            held.pop()

        api_limiter = MagicMock()
        api_limiter.run.side_effect = lambda **kwargs: nullcontext()
        dashboard_limiter = MagicMock()
        dashboard_limiter.run.side_effect = lambda **kwargs: nullcontext()
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.HARNESS_ROWS]
        runner = self._runner(sections)
        runner.is_query_service = True

        with (
            patch("posthog.hogql_queries.query_runner.app_org_concurrency_slot", side_effect=slot),
            patch("posthog.hogql_queries.query_runner.get_api_team_rate_limiter", return_value=api_limiter),
            patch(
                "posthog.hogql_queries.query_runner.get_app_dashboard_queries_rate_limiter",
                return_value=dashboard_limiter,
            ),
            patch.object(MCPDashboardQueryRunner, "_enforce_api_queries_budget") as budget_check,
            patch("posthog.hogql_queries.query_runner.tag_queries", wraps=tag_queries) as tag,
            tags_context(api_queries_budgeted=True),
        ):
            response = self._run(sections, runner=runner, query_id="q1", dashboard_id=7)

        assert response.error is None
        assert [c.kwargs["dashboard_id"] for c in dashboard_limiter.run.call_args_list] == [7, 7]
        assert org_slots == ["q1:toolRows", "q1:harnessRows"]
        assert most_held == 1
        assert [(c.kwargs["task_id"], c.kwargs["is_api"]) for c in api_limiter.run.call_args_list] == [
            ("q1:toolRows", True),
            ("q1:harnessRows", True),
        ]
        assert budget_check.call_count == len(sections)
        assert [c for c in tag.call_args_list if c.kwargs.get("chargeable") == 1] == [call(chargeable=1)] * len(
            sections
        )

    @parameterized.expand(
        [
            ("batched", [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.HARNESS_ROWS]),
            ("one_request_per_section", [MCPDashboardSection.HARNESS_ROWS]),
        ]
    )
    def test_each_section_keeps_the_timeout_its_standalone_query_had(
        self, _name: str, sections: list[MCPDashboardSection]
    ) -> None:
        limit_contexts: dict[str, LimitContext] = {}

        def record(*args: Any, **kwargs: Any) -> Any:
            limit_contexts[kwargs["query_type"]] = kwargs["limit_context"]
            return execute_hogql_query(*args, **kwargs)

        with (
            patch(f"{DASHBOARD_RUNNER}.execute_hogql_query", side_effect=record),
            patch(
                "products.mcp_analytics.backend.hogql_queries.harness_breakdown.execute_hogql_query",
                side_effect=record,
            ),
        ):
            self._run(sections)

        expected = {
            "mcp_dashboard_toolRows": LimitContext.QUERY_ASYNC,
            "mcp_harness_breakdown_query": LimitContext.QUERY,
        }
        assert limit_contexts == {key: expected[key] for key in limit_contexts}
        assert len(limit_contexts) == len(sections)

    def test_a_section_does_not_cache_another_sections_warehouse_warnings(self) -> None:
        warning = DataWarehouseSyncWarning(
            message="Sync failed",
            schema_name="invoices",
            source_type="Stripe",
            status="Failed",
            table_name="stripe_invoices",
        )

        def warn_from_tool_rows(*args: Any, **kwargs: Any) -> Any:
            if kwargs["query_type"] == "mcp_dashboard_toolRows":
                record_warnings([warning])
            return execute_hogql_query(*args, **kwargs)

        with patch(f"{DASHBOARD_RUNNER}.execute_hogql_query", side_effect=warn_from_tool_rows):
            self._run([MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.SESSION_ROWS])

        tool_rows = self._run([MCPDashboardSection.TOOL_ROWS])
        session_rows = self._run([MCPDashboardSection.SESSION_ROWS])
        assert tool_rows.is_cached and session_rows.is_cached
        assert [w.table_name for w in tool_rows.warnings or [] if isinstance(w, DataWarehouseSyncWarning)] == [
            "stripe_invoices"
        ]
        assert not session_rows.warnings

    def test_a_batch_that_finds_another_in_flight_still_returns_its_working_sections(self) -> None:
        self._seed()
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.KPIS]
        original = MCPDashboardQueryRunner._section_rows

        def fail_kpis(runner: MCPDashboardQueryRunner, section: MCPDashboardSection) -> Any:
            if section == MCPDashboardSection.KPIS:
                raise QueryError("KPI query is broken")
            return original(runner, section)

        released = FlightWait(outcome="released", last_refresh=None, failure=None)
        with (
            patch(
                "posthoganalytics.feature_enabled", side_effect=lambda key, *_, **__: key == QUERY_SINGLE_FLIGHT_FLAG
            ),
            patch.object(MCPDashboardQueryRunner, "_section_rows", autospec=True, side_effect=fail_kpis),
        ):
            self._run(sections)
            with (
                patch.object(QuerySingleFlight, "acquire", return_value=False),
                patch.object(QuerySingleFlight, "wait", return_value=released),
            ):
                response = self._run(sections)

        assert self._rows(response, MCPDashboardSection.TOOL_ROWS)
        assert response.results[MCPDashboardSection.KPIS.value].error is not None

    def test_a_forced_refresh_recomputes_cached_sections(self) -> None:
        self._seed()
        tools = MCPDashboardSection.TOOL_ROWS
        sections = [tools, MCPDashboardSection.SESSION_ROWS]
        self._run(sections)
        self._emit(1, "d10", "s10", "query_run", **{"$mcp_llm_model": "claude-opus-4-5"})
        flush_persons_and_events()

        cached = self._run(sections, execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        forced = self._run(sections, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        assert self._rows(forced, tools)[0][1] == self._rows(cached, tools)[0][1] + 1

    def test_a_batch_serves_a_cached_section_only_while_that_section_is_fresh(self) -> None:
        self._seed()
        tools = MCPDashboardSection.TOOL_ROWS
        sections = [tools, MCPDashboardSection.SESSION_ROWS]
        first = self._run([tools])
        self._emit(1, "d10", "s10", "query_run", **{"$mcp_llm_model": "claude-opus-4-5"})
        flush_persons_and_events()
        assert first.cache_target_age is not None

        with time_machine.travel(first.cache_target_age - timedelta(seconds=1), tick=False):
            before_expiry = self._run(sections)
        with time_machine.travel(first.cache_target_age + timedelta(seconds=1), tick=False):
            after_expiry = self._run(sections)

        assert before_expiry.last_refresh == first.last_refresh
        assert self._rows(after_expiry, tools)[0][1] == self._rows(before_expiry, tools)[0][1] + 1

    @parameterized.expand(
        [
            ("async_serves_fresh_sections", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE, "fresh", "cached"),
            ("async_dispatches_on_a_miss", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE, "partial", "job"),
            ("async_dispatches_when_stale", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE, "stale", "job"),
            (
                "lazy_async_dispatches_on_a_miss",
                ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
                "partial",
                "job",
            ),
            (
                "async_except_on_cache_miss_blocks_on_a_miss",
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
                "partial",
                "computed",
            ),
            (
                "async_except_on_cache_miss_dispatches_when_stale",
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
                "stale",
                "job",
            ),
        ]
    )
    def test_an_async_refresh_never_blocks_on_what_it_can_dispatch(
        self, _name: str, execution_mode: ExecutionMode, cache: str, expected: str
    ) -> None:
        self._seed()
        sections = [MCPDashboardSection.SESSION_ROWS, MCPDashboardSection.TOOL_ROWS]
        warmed = self._run(sections[:1] if cache == "partial" else sections)
        assert warmed.cache_target_age is not None
        moment = warmed.cache_target_age + timedelta(seconds=1) if cache == "stale" else datetime.now(UTC)

        with (
            time_machine.travel(moment, tick=False),
            patch.object(
                MCPDashboardQueryRunner,
                "enqueue_async_calculation",
                return_value=QueryStatus(id="job", team_id=self.team.pk),
            ) as enqueue,
        ):
            response = self._runner(sections).run(user=self.user, execution_mode=execution_mode)

        if expected == "job":
            assert isinstance(response, QueryStatusResponse)
            enqueue.assert_called_once()
            return
        assert isinstance(response, CachedMCPDashboardQueryResponse)
        assert enqueue.call_count == 0
        assert response.is_cached is (expected == "cached")
        assert self._rows(response, MCPDashboardSection.TOOL_ROWS)

    def test_the_request_cost_adds_up_every_sections_queries(self) -> None:
        self._seed()
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.SESSION_ROWS]
        bytes_read: list[int] = []
        with (
            tags_context(api_queries_budgeted=True),
            patch.object(MCPDashboardQueryRunner, "_enforce_api_queries_budget"),
            patch("posthog.clickhouse.client.execute.debit", return_value=5.0),
        ):
            # A first run also pays for lookups that later runs skip.
            self._run(sections, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            for section in sections:
                reset_request_query_cost()
                self._run([section], execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
                cost = get_request_query_cost()
                assert cost is not None
                bytes_read.append(cost.bytes_read)
            reset_request_query_cost()
            self._run(sections, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        cost = get_request_query_cost()
        assert cost is not None
        assert (cost.bytes_read, cost.remaining_bytes) == (sum(bytes_read), 5.0)

    def test_a_section_caches_the_query_scan_of_its_own_queries_only(self) -> None:
        self._seed()
        flag = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=10**9, event_ratio=0.1, persons_ratio=0.5)
        sessions = MCPDashboardSection.SESSION_ROWS
        with (
            patch("posthog.hogql_queries.query_runner.get_query_scan_flag", return_value=flag),
            patch("posthog.query_scan.serve.get_query_scan_flag", return_value=flag),
            patch("posthog.hogql_queries.query_runner.maybe_trigger_query_scan", return_value="below_floor"),
        ):
            sections = [MCPDashboardSection.TOOL_ROWS, sessions]
            # A first run also pays for lookups that later runs skip.
            self._run(sections, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            alone = self._run([sessions], execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            self._run(sections, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            cached = self._run([sessions])

        assert cached.is_cached
        assert alone.query_scan is not None and cached.query_scan is not None
        assert cached.query_scan.rows_read == alone.query_scan.rows_read

    # A worker thread cannot see the test transaction, so its sections fail. Its connections are what matter here.
    @override_settings(IN_UNIT_TESTING=False)
    def test_each_section_thread_closes_its_database_connections(self) -> None:
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.SESSION_ROWS]
        with patch.object(connections, "close_all", wraps=connections.close_all) as close_all:
            self._run(sections)

        assert close_all.call_count == len(sections)

    @parameterized.expand(
        [
            (
                "comparison_bucket",
                MCPDashboardSection.PERIOD_TOTALS,
                {"currentStartBucket": "2026-07-17 00:00:00"},
                True,
            ),
            ("comparison_start", MCPDashboardSection.KPIS, {"dateFrom": "2026-07-09T07:01:00.000Z"}, True),
            ("unread_comparison_start", MCPDashboardSection.TOOL_ROWS, {"dateFrom": "2026-07-09T07:01:00.000Z"}, False),
            (
                "unread_comparison_typed",
                MCPDashboardSection.HARNESS_ROWS,
                {"dateFrom": "2026-07-09T07:01:00.000Z"},
                False,
            ),
        ]
    )
    def test_the_cache_key_covers_the_comparison_window_only_where_a_section_reads_it(
        self, _name: str, section: MCPDashboardSection, change: dict[str, str], keyed: bool
    ) -> None:
        moved = self._runner([section], comparison=COMPARISON.model_copy(update=change))

        assert (moved.get_cache_key() != self._runner([section]).get_cache_key()) == keyed

    @parameterized.expand([("interval", {"interval": IntervalType.HOUR}), ("filters", {"filterTestAccounts": False})])
    def test_the_cache_key_covers_what_a_section_depends_on(self, _name: str, change: dict[str, Any]) -> None:
        sections = [MCPDashboardSection.PERIOD_TOTALS]

        assert self._runner(sections, **change).get_cache_key() != self._runner(sections).get_cache_key()

    def test_the_cache_key_covers_custom_harness_rules(self) -> None:
        sections = [MCPDashboardSection.HARNESS_ROWS, MCPDashboardSection.TOOL_ROWS]
        key = self._runner(sections).get_cache_key()

        with self.captureOnCommitCallbacks(execute=True):
            MCPCustomHarness.objects.create(team=self.team, name="Acme Agent", match_pattern="acme-agent")
            invalidate_custom_harness_rules(self.team)

        assert self._runner(sections).get_cache_key() != key
