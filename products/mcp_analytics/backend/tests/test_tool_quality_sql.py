from pathlib import Path

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
        "p99_duration_ms",
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


def test_tool_quality_sql_targets_canonical_mcp_tool_call_event() -> None:
    sql = TOOL_QUALITY_SQL_PATH.read_text()

    assert "event = '$mcp_tool_call'" in sql
    assert "$mcp_tool_name" in sql
