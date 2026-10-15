from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics import azure_log_analytics
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.azure_log_analytics import (
    AzureLogAnalyticsResumeConfig,
    AzureLogAnalyticsRetryableError,
    build_query,
    parse_table_names,
    rows_from_response,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.source import (
    AzureLogAnalyticsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureloganalytics import (
    AzureLogAnalyticsSourceConfig,
)

TENANT = "11111111-1111-1111-1111-111111111111"
WORKSPACE = "22222222-2222-2222-2222-222222222222"
TOKEN_PATH = f"/{TENANT}/oauth2/v2.0/token"
QUERY_PATH = f"/v1/workspaces/{WORKSPACE}/query"
COLUMNS = [
    {"name": "TimeGenerated", "type": "datetime"},
    {"name": "Message", "type": "string"},
    {"name": "Properties", "type": "dynamic"},
    {"name": "_ItemId", "type": "string"},
    {"name": "__posthog_cursor", "type": "string"},
]


def _config(tables: str | None = "AppTraces") -> AzureLogAnalyticsSourceConfig:
    return AzureLogAnalyticsSourceConfig(
        tenant_id=TENANT, client_id="client", client_secret="secret", workspace_id=WORKSPACE, tables=tables
    )


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"token_type": "Bearer", "expires_in": 3599, "access_token": "token-1"})


def _row(time_generated: str, item_id: str) -> list[Any]:
    return [time_generated, f"message {item_id}", '{"level": "info"}', item_id, time_generated]


def _page(rows: list[list[Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"tables": [{"name": "PrimaryResult", "columns": COLUMNS, "rows": rows}]})


def _queries(requests: list[RecordedRequest]) -> list[str]:
    return [request.json()["query"] for request in requests if request.path == QUERY_PATH]


# Every run in this class starts on 2026-10-02, so rows on earlier days fall in closed day windows.
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
WATERMARK_TODAY = {"incremental_field": "TimeGenerated", "db_incremental_field_last_value": "2026-10-02T09:30:00Z"}


def _min_start(start: str) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "tables": [{"name": "PrimaryResult", "columns": [{"name": "start", "type": "string"}], "rows": [[start]]}]
        }
    )


def _where_lines(query: str) -> list[str]:
    return [line for line in query.splitlines() if line.startswith("| where")]


class TestQueryWalk:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    def test_full_refresh_walks_day_windows_on_an_exact_cursor_and_stages_every_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(azure_log_analytics, "PAGE_SIZE", 2)
        # Both rows of the first page share one TimeGenerated, so only _ItemId separates them.
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {
                    TOKEN_PATH: [_token()],
                    QUERY_PATH: [
                        _min_start("2026-10-01T10:00:00.1234567Z"),
                        _page([_row("2026-10-01T10:00:00.1234567Z", "a"), _row("2026-10-01T10:00:00.1234567Z", "b")]),
                        _page([_row("2026-10-01T23:59:59.9999999Z", "c")]),
                        _page([_row("2026-10-02T08:00:00Z", "d")]),
                    ],
                }
            ),
        )

        assert result.raised is None
        queries = _queries(result.requests)
        assert queries[0] == "AppTraces | summarize start = min(TimeGenerated) | project start = tostring(start)"
        assert [_where_lines(query) for query in queries[1:]] == [
            [
                "| where TimeGenerated >= datetime(2026-10-01T10:00:00.1234567Z)",
                "| where TimeGenerated < datetime(2026-10-02T00:00:00Z)",
            ],
            [
                "| where TimeGenerated > datetime(2026-10-01T10:00:00.1234567Z) or "
                "(TimeGenerated == datetime(2026-10-01T10:00:00.1234567Z) and strcmp(_ItemId, 'b') > 0)",
                "| where TimeGenerated < datetime(2026-10-02T00:00:00Z)",
            ],
            ["| where TimeGenerated >= datetime(2026-10-02T00:00:00Z)"],
        ]
        assert all(query.endswith("| sort by TimeGenerated asc, _ItemId asc\n| take 2") for query in queries[1:])
        assert [row["_ItemId"] for row in result.rows] == ["a", "b", "c", "d"]
        assert all("__posthog_cursor" not in row for row in result.rows)
        assert result.saved_states == [
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-01T10:00:00.1234567Z", item_id="b"),
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-02T00:00:00Z"),
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-02T08:00:00Z", item_id="d"),
        ]
        assert result.committed_states == result.saved_states
        assert result.completed_state is None

    def test_empty_days_advance_the_window_without_rows(self) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {
                    TOKEN_PATH: [_token()],
                    QUERY_PATH: [_page([]), _page([]), _page([_row("2026-10-02T01:00:00Z", "z")])],
                }
            ),
            incremental_field="TimeGenerated",
            db_incremental_field_last_value=datetime(2026, 9, 30, 23, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert [_where_lines(query) for query in _queries(result.requests)] == [
            [
                "| where TimeGenerated >= datetime(2026-09-30T23:00:00.000000Z)",
                "| where TimeGenerated < datetime(2026-10-01T00:00:00Z)",
            ],
            [
                "| where TimeGenerated >= datetime(2026-10-01T00:00:00Z)",
                "| where TimeGenerated < datetime(2026-10-02T00:00:00Z)",
            ],
            ["| where TimeGenerated >= datetime(2026-10-02T00:00:00Z)"],
        ]
        assert [row["_ItemId"] for row in result.rows] == ["z"]

    @pytest.mark.parametrize(
        ("inputs", "expected_first_query"),
        [
            ({}, "AppTraces | summarize start = min(TimeGenerated) | project start = tostring(start)"),
            (
                {
                    "incremental_field": "TimeGenerated",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": datetime(2026, 10, 2, tzinfo=UTC),
                },
                "AppTraces | summarize start = min(TimeGenerated) | project start = tostring(start)",
            ),
        ],
    )
    def test_full_refresh_starts_at_the_oldest_row_and_stops_on_an_empty_table(
        self, inputs: dict[str, Any], expected_first_query: str
    ) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces", route({TOKEN_PATH: [_token()], QUERY_PATH: [_min_start("")]}), **inputs
        )

        assert result.raised is None
        assert _queries(result.requests) == [expected_first_query]
        assert result.rows == []

    def test_resume_starts_after_the_saved_row_and_ignores_the_watermark(self) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route({TOKEN_PATH: [_token()], QUERY_PATH: [_page([_row("2026-10-02T11:00:00Z", "z")])]}),
            resume_state=AzureLogAnalyticsResumeConfig(time_generated="2026-10-02T10:59:59.9999999Z", item_id="y"),
            incremental_field="TimeGenerated",
            db_incremental_field_last_value=datetime(2026, 10, 1, tzinfo=UTC),
        )

        assert result.raised is None
        (query,) = _queries(result.requests)
        assert "strcmp(_ItemId, 'y') > 0" in query
        assert ">= datetime(" not in query

    def test_a_page_over_the_size_limit_is_read_again_with_half_the_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(azure_log_analytics, "PAGE_SIZE", 400)
        too_large = ScriptedResponse(
            json={
                "tables": [{"name": "PrimaryResult", "columns": COLUMNS, "rows": [_row("2026-10-02T10:00:00Z", "a")]}],
                "error": {
                    "code": "PartialError",
                    "message": "Query result set has exceeded the internal data size limit",
                },
            }
        )
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route({TOKEN_PATH: [_token()], QUERY_PATH: [too_large, _page([_row("2026-10-02T10:00:00Z", "a")])]}),
            **WATERMARK_TODAY,
        )

        assert result.raised is None
        assert [query.splitlines()[-1] for query in _queries(result.requests)] == ["| take 400", "| take 200"]
        assert [row["_ItemId"] for row in result.rows] == ["a"]

    def test_a_partial_result_at_the_smallest_page_fails_the_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(azure_log_analytics, "PAGE_SIZE", 100)
        partial = ScriptedResponse(
            json={
                "tables": [{"name": "PrimaryResult", "columns": COLUMNS, "rows": [_row("2026-10-02T10:00:00Z", "a")]}],
                "error": {"code": "PartialError", "message": "There were some errors when processing your query."},
            }
        )
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces", route({TOKEN_PATH: [_token()], QUERY_PATH: [partial]}), **WATERMARK_TODAY
        )

        assert result.rows == []
        assert result.raised is not None and "PartialError" in str(result.raised)

    def test_expired_token_is_reminted_once(self) -> None:
        expired = ScriptedResponse(
            status=401, json={"error": {"code": "TokenExpired", "message": "The provided authentication has expired"}}
        )
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {TOKEN_PATH: [_token(), _token()], QUERY_PATH: [expired, _page([_row("2026-10-02T10:00:00Z", "a")])]}
            ),
            **WATERMARK_TODAY,
        )

        assert result.raised is None
        assert result.paths == [TOKEN_PATH, QUERY_PATH, TOKEN_PATH, QUERY_PATH]
        assert len(result.rows) == 1

    def test_retries_stop_before_a_full_attempt_would_overrun_five_minutes(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return _token()
            return ScriptedResponse(
                status=504, json={"error": {"code": "GatewayTimeout"}}, headers={"Retry-After": "30"}
            )

        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run("AppTraces", respond, **WATERMARK_TODAY)

        assert isinstance(result.raised, AzureLogAnalyticsRetryableError)
        # Waits at 0 s and 30 s leave room for a full 230 s attempt; a third retry at 60 s does not.
        assert len(_queries(result.requests)) == 3


class TestRowShaping:
    @pytest.mark.parametrize(
        ("column_type", "value", "expected"),
        [
            ("datetime", "2026-10-01T10:00:00.1234567Z", datetime(2026, 10, 1, 10, 0, 0, 123456, tzinfo=UTC)),
            ("dynamic", '{"a": [1, 2]}', {"a": [1, 2]}),
            ("dynamic", "not json", "not json"),
            ("bool", "True", True),
            ("bool", 0, False),
            ("long", 7, 7),
            ("string", None, None),
        ],
    )
    def test_converts_values_by_column_type(self, column_type: str, value: Any, expected: Any) -> None:
        payload = {"tables": [{"columns": [{"name": "c", "type": column_type}], "rows": [[value]]}]}

        assert rows_from_response(payload) == [{"c": expected}]


class TestInputs:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("AppTraces\n\nMyEvents_CL\nAppTraces", ["AppTraces", "MyEvents_CL"]),
            ("AppTraces, AppRequests", ["AppTraces", "AppRequests"]),
            (None, []),
        ],
    )
    def test_parses_one_table_per_line(self, raw: str | None, expected: list[str]) -> None:
        assert parse_table_names(raw) == expected

    @pytest.mark.parametrize("raw", ["AppTraces | union SecurityEvent", "App-Traces", "1Table"])
    def test_rejects_table_names_that_are_not_plain_identifiers(self, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_table_names(raw)

    @pytest.mark.parametrize(
        "resume",
        [
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-01) | union X", item_id="a"),
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-01T10:00:00Z", item_id="a') or true or ('"),
        ],
    )
    def test_rejects_a_resume_cursor_that_would_change_the_query(self, resume: AzureLogAnalyticsResumeConfig) -> None:
        with pytest.raises(ValueError):
            build_query("AppTraces", resume, None, 10)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("query_response", "table", "expected_ok", "expected_fragment"),
        [
            (_page([]), None, True, None),
            (
                ScriptedResponse(
                    status=403,
                    json={
                        "error": {
                            "code": "InsufficientAccessError",
                            "message": "The provided credentials have insufficient access to perform the requested operation",
                        }
                    },
                ),
                None,
                False,
                "Log Analytics Reader",
            ),
            (
                ScriptedResponse(
                    status=404,
                    json={"error": {"code": "WorkspaceNotFoundError", "message": "Workspace could not be found"}},
                ),
                None,
                False,
                "No Log Analytics workspace",
            ),
            (
                ScriptedResponse(
                    status=400,
                    json={
                        "error": {
                            "code": "BadArgumentError",
                            "message": "The request had some invalid properties",
                            "innererror": {
                                "code": "SemanticError",
                                "message": "A semantic error occurred.",
                                "innererror": {
                                    "code": "SEM0100",
                                    "message": "'take' operator: Failed to resolve table or column expression named 'NoSuchTable'",
                                },
                            },
                        }
                    },
                ),
                "NoSuchTable",
                False,
                "no table named NoSuchTable",
            ),
        ],
    )
    def test_maps_the_workspace_probe_to_a_message(
        self, query_response: ScriptedResponse, table: str | None, expected_ok: bool, expected_fragment: str | None
    ) -> None:
        with scripted_network(route({TOKEN_PATH: [_token()], QUERY_PATH: [query_response]})) as network:
            ok, message = validate_credentials(TENANT, "client", "secret", WORKSPACE, table)

        assert ok is expected_ok
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message
        probe = network.requests_log[-1].json()["query"]
        assert probe == (f"{table} | take 0" if table else "print ok = 1")

    def test_rejected_secret_stops_before_the_workspace_probe(self) -> None:
        rejected = ScriptedResponse(
            status=401,
            json={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."},
        )
        with scripted_network(route({TOKEN_PATH: [rejected]})) as network:
            ok, message = validate_credentials(TENANT, "client", "wrong", WORKSPACE)

        assert ok is False
        assert message is not None and "Microsoft Entra ID" in message
        assert [request.path for request in network.requests_log] == [TOKEN_PATH]


class TestSchemaDiscovery:
    def test_blank_table_list_discovers_tables_from_usage(self) -> None:
        usage = ScriptedResponse(
            json={
                "tables": [
                    {
                        "name": "PrimaryResult",
                        "columns": [{"name": "DataType", "type": "string"}],
                        "rows": [["AppRequests"], ["MyEvents_CL"], ["not a table"]],
                    }
                ]
            }
        )
        with scripted_network(route({TOKEN_PATH: [_token()], QUERY_PATH: [usage]})) as network:
            schemas = AzureLogAnalyticsSource().get_schemas(_config(tables=None), team_id=1)

        assert [schema.name for schema in schemas] == ["AppRequests", "MyEvents_CL"]
        assert network.requests_log[-1].json()["query"].startswith("Usage | where TimeGenerated > ago(30d)")

    def test_endpoint_permissions_flag_tables_the_query_api_cannot_read(self) -> None:
        basic_plan = ScriptedResponse(
            status=400,
            json={
                "error": {
                    "code": "BadArgumentError",
                    "message": "The request had some invalid properties",
                    "innererror": {"code": "SemanticError", "message": "Table 'BasicLogs_CL' has the Basic plan."},
                }
            },
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return _token()
            query = request.json()["query"]
            if query.startswith("BasicLogs_CL"):
                return basic_plan
            if query.startswith("Throttled"):
                return ScriptedResponse(status=429, json={}, headers={"Retry-After": "300"})
            return _page([])

        with scripted_network(respond):
            permissions = AzureLogAnalyticsSource().get_endpoint_permissions(
                _config(), team_id=1, endpoints=["AppTraces", "BasicLogs_CL", "Throttled"]
            )

        assert permissions["AppTraces"] is None
        assert permissions["Throttled"] is None
        assert permissions["BasicLogs_CL"] is not None and "Basic and Auxiliary" in permissions["BasicLogs_CL"]
