import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare_d1.cloudflare_d1 import (
    INVALID_ID_MESSAGE,
    INVALID_TOKEN_MESSAGE,
    NOT_FOUND_MESSAGE,
    UNREACHABLE_MESSAGE,
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
                # D1 answers a BLOB as a JSON array of byte values.
                shaped = [
                    {key: list(value) if isinstance(value, bytes) else value for key, value in dict(row).items()}
                    for row in rows
                ]
                results.append({"results": shaped, "success": True, "meta": {}})
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


def _page_sqls(result: Any) -> list[str]:
    return [sql for request in result.requests if "LIMIT" in (sql := request.json()["sql"])]


def _driver() -> SourceDriver:
    return SourceDriver(CloudflareD1Source(), CONFIG)


def test_full_refresh_walks_rowid_keyset_pages_to_the_short_page() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT);" + _insert("users", 2500)

    result = _driver().run("users", d1(setup))

    assert result.raised is None
    assert [row["id"] for row in result.rows] == list(range(1, 2501))
    assert all(set(row) == {"id", "name", "updated_at"} for row in result.rows)
    assert [state.last_values for state in result.committed_states] == [[1000], [2000], [2500]]
    assert "WHERE (rowid) > (2000)" in _page_sqls(result)[2]
    assert result.response is not None
    assert result.response.primary_keys == ["id"]
    assert result.response.rows_to_sync == 2500


def test_resume_continues_after_the_saved_keys() -> None:
    setup = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT);" + _insert("users", 2500)

    result = _driver().run("users", d1(setup), resume_state=D1ResumeConfig(last_values=[2000]))

    assert [row["id"] for row in result.rows] == list(range(2001, 2501))


@pytest.mark.parametrize(
    ("declared", "values", "watermark", "field_type", "expected_ids"),
    [
        # The second of the watermark comes again; earlier rows and NULLs stay out.
        (
            "DATETIME",
            [
                "'2024-01-02 03:04:04'",
                "'2024-01-02 03:04:05'",
                "'2024-01-02 03:04:05.500'",
                "NULL",
                "'2024-01-03 00:00:00'",
            ],
            datetime(2024, 1, 2, 3, 4, 5, 250000, tzinfo=UTC),
            IncrementalFieldType.DateTime,
            [2, 3, 5],
        ),
        (
            "TIMESTAMP",
            ["'2024-01-02T03:04:04Z'", "'2024-01-02T03:04:05.123Z'", "'2024-01-02T03:04:06Z'"],
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            IncrementalFieldType.DateTime,
            [2, 3],
        ),
        ("DATE", ["'2024-01-01'", "'2024-01-02'", "'2024-01-03'"], date(2024, 1, 2), IncrementalFieldType.Date, [2, 3]),
        (
            "DATETIME",
            ["1704164644", "1704164645", "1704164700"],
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            IncrementalFieldType.DateTime,
            [2, 3],
        ),
        ("INTEGER", ["10", "20", "30"], 20, IncrementalFieldType.Integer, [2, 3]),
    ],
    ids=["space-separated", "iso-with-zone", "date-only", "epoch-seconds", "integer"],
)
def test_incremental_bound_matches_the_form_the_column_stores(
    declared: str, values: list[str], watermark: Any, field_type: IncrementalFieldType, expected_ids: list[int]
) -> None:
    rows = ", ".join(f"({i}, {value})" for i, value in enumerate(values, start=1))
    setup = f"CREATE TABLE events (id INTEGER PRIMARY KEY, changed {declared}); INSERT INTO events VALUES {rows};"

    result = _driver().run(
        "events",
        d1(setup),
        incremental_field="changed",
        incremental_field_type=field_type,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == expected_ids


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


def test_without_rowid_table_pages_by_primary_key_keyset() -> None:
    setup = "CREATE TABLE tags (slug TEXT PRIMARY KEY, label TEXT) WITHOUT ROWID;" + "".join(
        f"INSERT INTO tags VALUES ('tag-{i:04d}', 'Tag {i}');" for i in range(1200, 0, -1)
    )

    result = _driver().run("tags", d1(setup))

    assert [row["slug"] for row in result.rows] == [f"tag-{i:04d}" for i in range(1, 1201)]
    assert [state.last_values for state in result.committed_states] == [["tag-1000"], ["tag-1200"]]
    assert not any("OFFSET" in sql for sql in _page_sqls(result))


def test_a_blob_primary_key_pages_by_offset_instead_of_a_keyset_it_cannot_bind() -> None:
    setup = "CREATE TABLE files (digest BLOB PRIMARY KEY, name TEXT) WITHOUT ROWID;" + "".join(
        f"INSERT INTO files VALUES (randomblob(8), 'f{i}');" for i in range(1200)
    )

    result = _driver().run("files", d1(setup))

    assert result.raised is None
    assert len(result.rows) == 1200
    assert [state.offset for state in result.committed_states] == [1000, 1200]


def test_a_view_without_keys_pages_by_offset() -> None:
    setup = (
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT);"
        + _insert("users", 1200)
        + "CREATE VIEW recent AS SELECT id, name FROM users;"
    )

    result = _driver().run("recent", d1(setup))

    assert len(result.rows) == 1200
    assert [state.offset for state in result.committed_states] == [1000, 1200]


def test_user_columns_named_like_the_rowid_survive_and_paging_still_uses_the_hidden_rowid() -> None:
    setup = "CREATE TABLE logs (rowid TEXT, __posthog_rowid TEXT, message TEXT);" + "".join(
        f"INSERT INTO logs VALUES ('same', 'mine-{i}', 'm{i}');" for i in range(1, 1201)
    )

    result = _driver().run("logs", d1(setup))

    assert result.raised is None
    assert [row["message"] for row in result.rows] == [f"m{i}" for i in range(1, 1201)]
    assert result.rows[0] == {"rowid": "same", "__posthog_rowid": "mine-1", "message": "m1"}
    assert "(_rowid_) > (1000)" in _page_sqls(result)[1]


def test_a_table_that_is_gone_fails_with_a_message_the_source_maps() -> None:
    result = _driver().run("users", d1("CREATE TABLE orders (id INTEGER PRIMARY KEY);"))

    assert isinstance(result.raised, D1QueryError)
    assert "no such table: users" in str(result.raised)


def test_a_dropped_incremental_column_fails_instead_of_syncing_nothing() -> None:
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
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, score REAL, created_at TIMESTAMP, born DATE, opens TIME, data BLOB);
        CREATE INDEX users_created_at ON users (created_at);
        CREATE VIEW recent_events AS SELECT 1 AS n, CURRENT_TIMESTAMP AS at;
        CREATE TABLE _cf_KV (key TEXT PRIMARY KEY, value BLOB);
        CREATE TABLE memberships (user_id INTEGER, team_id INTEGER, PRIMARY KEY (team_id, user_id));
        CREATE VIEW active_users AS SELECT id FROM users;
    """

    with scripted_network(d1(setup)):
        schemas = {schema.name: schema for schema in CloudflareD1Source().get_schemas(CONFIG, team_id=1)}

    assert sorted(schemas) == ["active_users", "memberships", "recent_events", "users"]
    assert [(field["field"], field["type"], field["is_indexed"]) for field in schemas["users"].incremental_fields] == [
        ("id", IncrementalFieldType.Integer, True),
        ("score", IncrementalFieldType.Numeric, False),
        ("created_at", IncrementalFieldType.DateTime, True),
        ("born", IncrementalFieldType.Date, False),
    ]
    # A view pages by offset, and an offset breaks once a later attempt moves the watermark.
    assert schemas["recent_events"].incremental_fields == []
    assert schemas["recent_events"].supports_incremental is False
    assert schemas["memberships"].detected_primary_keys == ["team_id", "user_id"]
    assert schemas["active_users"].detected_primary_keys is None


def test_schemas_return_only_the_names_the_caller_asked_for() -> None:
    # The shared schema contract test cannot drive this source, because the table list comes from
    # the database, so the filter keeps its check here.
    setup = """
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE orders (id INTEGER PRIMARY KEY);
    """
    source = CloudflareD1Source()

    def names_for(names: list[str] | None) -> list[str]:
        with scripted_network(d1(setup)):
            return sorted(schema.name for schema in source.get_schemas(CONFIG, team_id=1, names=names))

    assert names_for(None) == ["orders", "users"]
    assert names_for(["users"]) == ["users"]
    assert names_for(["users", "missing"]) == ["users"]
    # An empty list names no table, so it is not a request for all of them.
    assert names_for([]) == []


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


def test_validate_credentials_reports_an_unreachable_api_instead_of_raising() -> None:
    # The API calls the probe while a person creates the source, so a raised error would show them a
    # generic failure instead of what went wrong.
    with scripted_network(always(requests.ConnectionError("connection refused"))):
        assert CloudflareD1Source().validate_credentials(CONFIG, team_id=1) == (False, UNREACHABLE_MESSAGE)


def test_an_id_that_could_change_the_api_path_is_refused_without_a_request() -> None:
    config = CloudflareD1SourceConfig(api_token="cf-token", account_id="0123456789abcdef", database_id="../../user")

    with scripted_network(always(ScriptedResponse(status=500))) as network:
        assert CloudflareD1Source().validate_credentials(config, team_id=1) == (False, INVALID_ID_MESSAGE)

    assert network.requests_log == []
