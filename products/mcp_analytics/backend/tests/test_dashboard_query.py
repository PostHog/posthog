import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, call, patch

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
    MCPDashboardSection,
    MCPHarnessBreakdownQuery,
    MCPModelBreakdownQuery,
    MCPProtocolVersionBreakdownQuery,
    MCPToolCallBreakdownQuery,
    MCPToolCallsAndErrorsQuery,
    PropertyOperator,
)

from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.warehouse_warnings import record_warnings

from posthog.clickhouse.query_tagging import tag_queries, tags_context
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.query_cache.single_flight import QUERY_SINGLE_FLIGHT_FLAG, FlightWait, QuerySingleFlight

from products.mcp_analytics.backend.facade.api import invalidate_custom_harness_rules
from products.mcp_analytics.backend.hogql_queries.dashboard_query import MCPDashboardQueryRunner
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

    def _rows(self, response: CachedMCPDashboardQueryResponse, section: MCPDashboardSection) -> Any:
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

    def test_a_batch_returns_each_section_as_its_own_query_would(self) -> None:
        self._seed()
        sections = list(MCPDashboardSection)

        batch = self._run(sections)

        assert list(batch.results) == [section.value for section in sections]
        assert batch.error is None
        for section in sections:
            assert self._rows(batch, section) == self._rows(self._run([section]), section), section

    def test_a_failed_section_leaves_the_others_and_keeps_the_batch_uncached(self) -> None:
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
        assert first.error is not None and MCPDashboardSection.KPIS.value in first.error
        assert self._rows(first, MCPDashboardSection.TOOL_ROWS)
        assert self._rows(first, MCPDashboardSection.HARNESS_ROWS)
        assert second.is_cached is False
        assert self._run([MCPDashboardSection.TOOL_ROWS]).is_cached is True
        assert self._run([MCPDashboardSection.KPIS]).is_cached is False

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
        sections = [MCPDashboardSection.TOOL_ROWS, MCPDashboardSection.HARNESS_ROWS]
        runner = self._runner(sections)
        runner.is_query_service = True

        with (
            patch("posthog.hogql_queries.query_runner.app_org_concurrency_slot", side_effect=slot),
            patch("posthog.hogql_queries.query_runner.get_api_team_rate_limiter", return_value=api_limiter),
            patch.object(MCPDashboardQueryRunner, "_enforce_api_queries_budget") as budget_check,
            patch("posthog.hogql_queries.query_runner.tag_queries", wraps=tag_queries) as tag,
            tags_context(api_queries_budgeted=True),
        ):
            response = self._run(sections, runner=runner, query_id="q1")

        assert response.error is None
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
        sections = [MCPDashboardSection.NAMED_MODEL_USERS, MCPDashboardSection.TOOL_ROWS]
        self._run(sections)
        self._emit(1, "d10", "s10", "query_run", **{"$mcp_llm_model": "claude-opus-4-5"})
        flush_persons_and_events()

        cached = self._run(sections, execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        forced = self._run(sections, execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        users = MCPDashboardSection.NAMED_MODEL_USERS
        assert self._rows(forced, users)[0][0] == self._rows(cached, users)[0][0] + 1

    @parameterized.expand(
        [
            ("comparison", {"comparison": COMPARISON.model_copy(update={"currentStartBucket": "2026-07-17 00:00:00"})}),
            ("interval", {"interval": IntervalType.HOUR}),
            ("filters", {"filterTestAccounts": False}),
        ]
    )
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
