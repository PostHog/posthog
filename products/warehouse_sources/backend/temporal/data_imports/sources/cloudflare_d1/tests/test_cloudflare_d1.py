import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_d1.cloudflare_d1 import (
    INVALID_ID_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    NOT_FOUND_MESSAGE,
    D1QueryError,
    D1ResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_d1.source import CloudflareD1Source
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflared1 import (
    CloudflareD1SourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

CONFIG = CloudflareD1SourceConfig(api_token="cf-token", account_id="0123456789abcdef", database_id="db-00000000")


def d1(setup: str) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the D1 query endpoint from an in-memory SQLite database, in D1's response envelope."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(setup)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        body = request.json()
        results: list[dict[str, Any]] = []
        try:
            for statement in body["sql"].split("; "):
                rows = connection.execute(statement, body.get("params") or []).fetchall()
                results.append({"results": [dict(row) for row in rows], "success": True, "meta": {}})
        except sqlite3.Error as error:
            return ScriptedResponse(
                status=400,
                json={"result": [], "success": False, "errors": [{"code": 7500, "message": f"{error}: SQLITE_ERROR"}]},
            )
        return ScriptedResponse(json={"result": results, "success": True, "errors": [], "messages": []})

    return respond


def _insert(table: str, count: int, updated_at: str = "2024-01-01 00:00:00") -> str:
    values = ", ".join(f"({i}, 'name-{i}', '{updated_at}')" for i in range(1, count + 1))
    return f"INSERT INTO {table} (id, name, updated_at) VALUES {values};"


def _sqls(result: Any) -> list[str]:
    return [request.json()["sql"] for request in result.requests]


def _driver() -> SourceDriver:
    return SourceDriver(CloudflareD1Source(), CONFIG)


def test_full_refresh_walks_rowid_pages_to_the_short_page() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT);" + _insert("users", 2500)

    result = _driver().run("users", d1(setup))

    assert result.raised is None
    assert [row["id"] for row in result.rows] == list(range(1, 2501))
    assert all("__rowid" not in row for row in result.rows)
    assert [state.last_rowid for state in result.committed_states] == [1000, 2000, 2500]
    page_sqls = [sql for sql in _sqls(result) if sql.startswith("SELECT rowid")]
    assert len(page_sqls) == 3
    assert "WHERE rowid > 2000" in page_sqls[2]
    assert result.response is not None
    assert result.response.primary_keys == ["id"]
    assert result.response.rows_to_sync == 2500


def test_resume_starts_after_the_saved_rowid() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT);" + _insert("users", 2500)

    result = _driver().run("users", d1(setup), resume_state=D1ResumeConfig(table="users", last_rowid=2000))

    assert [row["id"] for row in result.rows] == list(range(2001, 2501))


def test_saved_state_for_another_table_is_ignored() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT);" + _insert("users", 3)

    result = _driver().run("users", d1(setup), resume_state=D1ResumeConfig(table="orders", last_rowid=2))

    assert [row["id"] for row in result.rows] == [1, 2, 3]


def test_incremental_compares_dates_written_in_different_text_forms() -> None:
    setup = """
        CREATE TABLE events (id INTEGER PRIMARY KEY, updated_at DATETIME);
        INSERT INTO events VALUES
            (1, '2024-01-02 03:04:05'),
            (2, '2024-01-02T03:04:06Z'),
            (3, '2024-01-02 03:04:05.500'),
            (4, NULL),
            (5, '2024-01-01T23:00:00-05:00'),
            (6, '2024-01-01 12:00:00');
    """

    result = _driver().run(
        "events",
        d1(setup),
        incremental_field="updated_at",
        incremental_field_type=IncrementalFieldType.DateTime,
        db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == [3, 2, 5]


def test_incremental_keyset_does_not_skip_or_repeat_rows_sharing_one_value() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at DATETIME);" + _insert("users", 2500)

    result = _driver().run(
        "users",
        d1(setup),
        incremental_field="updated_at",
        incremental_field_type=IncrementalFieldType.DateTime,
    )

    assert [row["id"] for row in result.rows] == list(range(1, 2501))
    assert result.response is not None
    assert result.response.rows_to_sync is None


def test_without_rowid_table_pages_by_offset_in_primary_key_order() -> None:
    setup = "CREATE TABLE tags (slug TEXT PRIMARY KEY, label TEXT) WITHOUT ROWID;" + "".join(
        f"INSERT INTO tags VALUES ('tag-{i:04d}', 'Tag {i}');" for i in range(1200, 0, -1)
    )

    result = _driver().run("tags", d1(setup))

    assert [row["slug"] for row in result.rows] == [f"tag-{i:04d}" for i in range(1, 1201)]
    assert [state.offset for state in result.committed_states] == [1000, 1200]


def test_a_table_that_is_gone_fails_with_a_message_the_source_maps() -> None:
    result = _driver().run("users", d1("CREATE TABLE orders (id INTEGER PRIMARY KEY);"))

    assert isinstance(result.raised, D1QueryError)
    assert "no such table: users" in str(result.raised)


def test_sql_error_text_from_the_envelope_reaches_the_error() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, updated_at DATETIME);"

    result = _driver().run(
        "users",
        d1(setup),
        incremental_field="deleted_column",
        incremental_field_type=IncrementalFieldType.DateTime,
    )

    assert isinstance(result.raised, D1QueryError)
    assert "no such column" in str(result.raised)


def test_schemas_hide_internal_tables_and_offer_only_comparable_columns() -> None:
    setup = """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, score REAL, created_at TIMESTAMP, data BLOB);
        CREATE TABLE _cf_KV (key TEXT PRIMARY KEY, value BLOB);
        CREATE TABLE memberships (user_id INTEGER, team_id INTEGER, PRIMARY KEY (team_id, user_id));
        CREATE VIEW active_users AS SELECT id FROM users;
    """

    with scripted_network(d1(setup)):
        schemas = {schema.name: schema for schema in CloudflareD1Source().get_schemas(CONFIG, team_id=1)}

    assert sorted(schemas) == ["active_users", "memberships", "users"]
    assert [field["field"] for field in schemas["users"].incremental_fields] == ["id", "score", "created_at"]
    assert schemas["memberships"].detected_primary_keys == ["team_id", "user_id"]
    assert schemas["active_users"].detected_primary_keys is None


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, {"result": {"uuid": "db-00000000", "name": "prod"}, "success": True}, None),
        (
            401,
            {"result": None, "success": False, "errors": [{"code": 10000, "message": "Authentication error"}]},
            INVALID_TOKEN_MESSAGE,
        ),
        (
            404,
            {
                "result": None,
                "success": False,
                "errors": [{"code": 7404, "message": "The database could not be found"}],
            },
            NOT_FOUND_MESSAGE,
        ),
    ],
)
def test_validate_credentials_maps_cloudflare_answers(status: int, body: dict[str, Any], expected: str | None) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
        valid, message = CloudflareD1Source().validate_credentials(CONFIG, team_id=1)

    assert (valid, message) == (expected is None, expected)
    assert network.requests_log[0].path == "/client/v4/accounts/0123456789abcdef/d1/database/db-00000000"


def test_an_id_that_could_change_the_api_path_is_refused_without_a_request() -> None:
    config = CloudflareD1SourceConfig(api_token="cf-token", account_id="0123456789abcdef", database_id="../../user")

    with scripted_network(always(ScriptedResponse(status=500))) as network:
        assert CloudflareD1Source().validate_credentials(config, team_id=1) == (False, INVALID_ID_MESSAGE)

    assert network.requests_log == []
