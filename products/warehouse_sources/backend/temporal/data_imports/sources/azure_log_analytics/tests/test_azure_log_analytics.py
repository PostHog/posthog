from datetime import UTC, datetime
from typing import Any

import pytest

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


class TestQueryWalk:
    def test_walks_full_pages_on_an_exact_cursor_and_stages_each_before_its_page(
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
                        _page([_row("2026-10-01T10:00:00.1234567Z", "a"), _row("2026-10-01T10:00:00.1234567Z", "b")]),
                        _page([_row("2026-10-01T10:00:01Z", "c"), _row("2026-10-01T10:00:02.5Z", "d")]),
                        _page([_row("2026-10-01T10:00:03Z", "e")]),
                    ],
                }
            ),
        )

        assert result.raised is None
        queries = _queries(result.requests)
        assert len(queries) == 3
        assert "where" not in queries[0]
        assert (
            "| where TimeGenerated > datetime(2026-10-01T10:00:00.1234567Z) or "
            "(TimeGenerated == datetime(2026-10-01T10:00:00.1234567Z) and strcmp(_ItemId, 'b') > 0)"
        ) in queries[1]
        assert "strcmp(_ItemId, 'd') > 0" in queries[2]
        assert all(query.endswith("| sort by TimeGenerated asc, _ItemId asc\n| take 2") for query in queries)
        assert [row["_ItemId"] for row in result.rows] == ["a", "b", "c", "d", "e"]
        assert all("__posthog_cursor" not in row for row in result.rows)
        assert result.saved_states == [
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-01T10:00:00.1234567Z", item_id="b"),
            AzureLogAnalyticsResumeConfig(time_generated="2026-10-01T10:00:02.5Z", item_id="d"),
        ]
        assert result.committed_states == result.saved_states
        assert result.completed_state is None

    @pytest.mark.parametrize(
        ("inputs", "expected_filter"),
        [
            ({}, None),
            (
                {
                    "incremental_field": "TimeGenerated",
                    "db_incremental_field_last_value": datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
                },
                "| where TimeGenerated >= datetime(2026-10-01T09:30:00.000000Z)",
            ),
            (
                {"incremental_field": "TimeGenerated", "db_incremental_field_last_value": "2026-10-01T09:30:00.5Z"},
                "| where TimeGenerated >= datetime(2026-10-01T09:30:00.5Z)",
            ),
            (
                {
                    "incremental_field": "TimeGenerated",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": datetime(2026, 10, 1, tzinfo=UTC),
                },
                None,
            ),
        ],
    )
    def test_incremental_run_filters_on_time_generated_and_full_refresh_does_not(
        self, inputs: dict[str, Any], expected_filter: str | None
    ) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces", route({TOKEN_PATH: [_token()], QUERY_PATH: [_page([])]}), **inputs
        )

        assert result.raised is None
        (query,) = _queries(result.requests)
        if expected_filter is None:
            assert "where" not in query
        else:
            assert expected_filter in query.splitlines()

    def test_resume_starts_after_the_saved_row_and_ignores_the_watermark(self) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route({TOKEN_PATH: [_token()], QUERY_PATH: [_page([_row("2026-10-01T11:00:00Z", "z")])]}),
            resume_state=AzureLogAnalyticsResumeConfig(time_generated="2026-10-01T10:59:59.9999999Z", item_id="y"),
            incremental_field="TimeGenerated",
            db_incremental_field_last_value=datetime(2026, 10, 1, tzinfo=UTC),
        )

        assert result.raised is None
        (query,) = _queries(result.requests)
        assert "strcmp(_ItemId, 'y') > 0" in query
        assert ">= datetime(" not in query

    def test_expired_token_is_reminted_once(self) -> None:
        expired = ScriptedResponse(
            status=401, json={"error": {"code": "TokenExpired", "message": "The provided authentication has expired"}}
        )
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {TOKEN_PATH: [_token(), _token()], QUERY_PATH: [expired, _page([_row("2026-10-01T10:00:00Z", "a")])]}
            ),
        )

        assert result.raised is None
        assert result.paths == [TOKEN_PATH, QUERY_PATH, TOKEN_PATH, QUERY_PATH]
        assert len(result.rows) == 1

    def test_throttle_that_outlives_the_budget_raises_a_retryable_error(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return _token()
            return ScriptedResponse(
                status=429, json={"error": {"code": "TooManyRequests"}}, headers={"Retry-After": "86400"}
            )

        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run("AppTraces", respond)

        assert isinstance(result.raised, AzureLogAnalyticsRetryableError)

    def test_partial_result_fails_the_run_instead_of_dropping_rows(self) -> None:
        partial = ScriptedResponse(
            json={
                "tables": [{"name": "PrimaryResult", "columns": COLUMNS, "rows": [_row("2026-10-01T10:00:00Z", "a")]}],
                "error": {"code": "PartialError", "message": "There were some errors when processing your query."},
            }
        )
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces", route({TOKEN_PATH: [_token()], QUERY_PATH: [partial]})
        )

        assert result.rows == []
        assert result.raised is not None and "PartialError" in str(result.raised)


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
