from datetime import UTC, datetime
from pathlib import Path

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
TOOL_QUALITY_SQL_PATH = TEMPLATES_DIR / "tool_quality.sql"


def test_tool_quality_sql_exists() -> None:
    assert TOOL_QUALITY_SQL_PATH.is_file()


def test_tool_quality_sql_contains_required_columns() -> None:
    sql = TOOL_QUALITY_SQL_PATH.read_text()

    # Aliased output columns the frontend table relies on.
    for column in (
        "tool",
        "total_calls",
        "error_rate_pct",
        "p50_duration_ms",
        "p95_duration_ms",
        "users",
        "sessions",
        "first_seen",
        "last_seen",
    ):
        assert f" {column}" in sql, f"missing column alias '{column}' in tool_quality.sql"


def test_tool_quality_sql_supports_filters_and_sort_placeholders() -> None:
    sql = TOOL_QUALITY_SQL_PATH.read_text()

    # The HogQL engine resolves {filters} from the wrapping HogQLQuery node.
    assert "{filters}" in sql
    # The frontend logic does .replace() on these markers before sending the query.
    assert "__ORDER_BY__" in sql
    assert "__ORDER_DIRECTION__" in sql


def test_tool_quality_sql_targets_mcp_tool_call_event() -> None:
    sql = TOOL_QUALITY_SQL_PATH.read_text()

    assert "event = 'mcp_tool_call'" in sql
    assert "$mcp_tool_name" in sql


def test_tool_quality_sql_resolves_all_event_shapes() -> None:
    sql = TOOL_QUALITY_SQL_PATH.read_text()

    # The effective-tool coalesce must cover all three producer shapes
    # (mirrored in frontend/mcpEventShape.ts).
    assert "$mcp_exec_tool_call_name" in sql
    assert "properties.tool_name" in sql
    # Legacy exec inner-call events carry `success` instead of $mcp_is_error
    # and `duration_ms` instead of $mcp_duration_ms.
    assert "properties.success" in sql
    assert "properties.duration_ms" in sql


def test_tool_quality_sql_excludes_exec_wrapper() -> None:
    sql = TOOL_QUALITY_SQL_PATH.read_text()

    assert "!= 'exec'" in sql


class TestToolQualitySQLExecution(ClickhouseTestMixin, APIBaseTest):
    def _seed(self, properties: dict) -> None:
        _create_event(
            team=self.team,
            event="mcp_tool_call",
            distinct_id="seed",
            timestamp=datetime.now(tz=UTC),
            properties=properties,
        )

    def test_aggregates_every_event_shape_and_drops_the_exec_wrapper(self) -> None:
        # Native tools/call shape (hono tools mode + SDK wrapping path).
        self._seed({"$mcp_tool_name": "query-logs", "$mcp_is_error": False, "$mcp_duration_ms": 100})
        # SDK single-exec shape: real tool rides in $mcp_exec_tool_call_name.
        self._seed(
            {
                "$mcp_tool_name": "exec",
                "$mcp_exec_tool_call_name": "query-logs",
                "$mcp_is_error": True,
                "$mcp_duration_ms": 10,
            }
        )
        # Legacy hono exec inner-call shape: snake_case keys only.
        self._seed({"tool_name": "apm-trace-get", "success": False, "duration_ms": 50})
        # Hono outer exec wrapper: must not produce a row.
        self._seed({"$mcp_tool_name": "exec", "$mcp_is_error": False, "$mcp_duration_ms": 999})

        sql = (
            TOOL_QUALITY_SQL_PATH.read_text()
            .replace("__ORDER_BY__", "total_calls")
            .replace("__ORDER_DIRECTION__", "DESC")
        )
        query = parse_select(sql, placeholders={"filters": ast.Constant(value=True)})
        response = execute_hogql_query(query=query, team=self.team)

        rows = {row[0]: row for row in response.results or []}
        assert set(rows) == {"query-logs", "apm-trace-get"}
        # query-logs: the native call + the SDK single-exec call, one of which errored.
        assert rows["query-logs"][1] == 2
        assert rows["query-logs"][2] == 1
        # apm-trace-get: the legacy inner-call shape, counted with its error and duration.
        assert rows["apm-trace-get"][1] == 1
        assert rows["apm-trace-get"][2] == 1
        assert rows["apm-trace-get"][4] == 50
