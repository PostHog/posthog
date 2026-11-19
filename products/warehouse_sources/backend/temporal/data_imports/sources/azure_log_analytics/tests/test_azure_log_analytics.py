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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.source import (
    AzureLogAnalyticsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureloganalytics import (
    AzureLogAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tests.contract_harness import check_extraction

TENANT = "11111111-1111-1111-1111-111111111111"
WORKSPACE = "22222222-2222-2222-2222-222222222222"
TOKEN_PATH = f"/{TENANT}/oauth2/v2.0/token"
QUERY_PATH = f"/v1/workspaces/{WORKSPACE}/query"
COLUMNS = [
    {"name": "TimeGenerated", "type": "datetime"},
    {"name": "_IngestionTime", "type": "datetime"},
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


def _row(ingested_at: str, item_id: str) -> list[Any]:
    return [ingested_at, ingested_at, f"message {item_id}", '{"level": "info"}', item_id, ingested_at]


def _missing(table: str) -> ScriptedResponse:
    return ScriptedResponse(
        status=400,
        json={
            "error": {
                "code": "BadArgumentError",
                "message": "The request had some invalid properties",
                "innererror": {
                    "code": "SemanticError",
                    "message": f"'take' operator: Failed to resolve table or column expression named '{table}'",
                },
            }
        },
    )


def _page(rows: list[list[Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"tables": [{"name": "PrimaryResult", "columns": COLUMNS, "rows": rows}]})


def _queries(requests: list[RecordedRequest]) -> list[str]:
    return [request.json()["query"] for request in requests if request.path == QUERY_PATH]


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
RUN_END = "2026-10-02T12:00:00.000000Z"
WATERMARK_TODAY = {"incremental_field": "_IngestionTime", "db_incremental_field_last_value": "2026-10-02T09:30:00Z"}
MIN_QUERY = "AppTraces | summarize start = min(ingestion_time()) | project start = tostring(start)"


def _min_start(start: str) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "tables": [{"name": "PrimaryResult", "columns": [{"name": "start", "type": "string"}], "rows": [[start]]}]
        }
    )


def _where_lines(query: str) -> list[str]:
    return [line for line in query.splitlines() if line.startswith("| where")]


def _window_end(query: str) -> str:
    return next(line for line in query.splitlines() if line.startswith("| where ingestion_time() < "))[
        len("| where ingestion_time() < datetime(") : -1
    ]


def _take(query: str) -> str:
    return next(line for line in query.splitlines() if line.startswith("| take "))


class TestQueryWalk:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    def test_full_refresh_walks_an_exact_cursor_and_stages_every_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(azure_log_analytics, "PAGE_SIZE", 2)
        # Both rows of the first page share one ingestion time, so only _ItemId separates them.
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {
                    TOKEN_PATH: [_token()],
                    QUERY_PATH: [
                        _min_start("2026-10-01T23:00:00.1234567Z"),
                        _page([_row("2026-10-01T23:00:00.1234567Z", "a"), _row("2026-10-01T23:00:00.1234567Z", "b")]),
                        _page([_row("2026-10-01T23:59:59.9999999Z", "c")]),
                        _page([_row("2026-10-02T08:00:00Z", "d")]),
                    ],
                }
            ),
        )

        assert result.raised is None
        queries = _queries(result.requests)
        assert queries[0] == MIN_QUERY
        assert [_where_lines(query) for query in queries[1:]] == [
            [
                "| where TimeGenerated >= datetime(2026-10-01T23:00:00.1234567Z) - 3d",
                "| where ingestion_time() >= datetime(2026-10-01T23:00:00.1234567Z)",
                "| where ingestion_time() < datetime(2026-10-02T00:00:00Z)",
            ],
            [
                "| where TimeGenerated >= datetime(2026-10-01T23:00:00.1234567Z) - 3d",
                "| where ingestion_time() > datetime(2026-10-01T23:00:00.1234567Z) or "
                "(ingestion_time() == datetime(2026-10-01T23:00:00.1234567Z) and strcmp(_ItemId, 'b') > 0)",
                "| where ingestion_time() < datetime(2026-10-02T00:00:00Z)",
            ],
            [
                "| where TimeGenerated >= datetime(2026-10-02T00:00:00Z) - 3d",
                "| where ingestion_time() >= datetime(2026-10-02T00:00:00Z)",
                f"| where ingestion_time() < datetime({RUN_END})",
            ],
        ]
        assert all(
            "| sort by _IngestionTime asc, _ItemId asc\n| take 2\n| extend _ItemId = _ItemId" in query
            for query in queries[1:]
        )
        assert [row["_ItemId"] for row in result.rows] == ["a", "b", "c", "d"]
        assert all("__posthog_cursor" not in row for row in result.rows)
        assert result.saved_states == [
            AzureLogAnalyticsResumeConfig(ingested_at="2026-10-01T23:00:00.1234567Z", item_id="b"),
            AzureLogAnalyticsResumeConfig(ingested_at="2026-10-02T00:00:00Z"),
            AzureLogAnalyticsResumeConfig(ingested_at=RUN_END),
        ]
        assert result.committed_states == result.saved_states
        assert result.completed_state is None

    def test_a_full_page_narrows_the_rest_of_that_day_to_hour_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(azure_log_analytics, "PAGE_SIZE", 2)
        answers = iter([_page([_row("2026-10-01T22:40:00Z", "a"), _row("2026-10-01T22:41:00Z", "b")])])

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return _token()
            return next(answers, _page([]))

        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            respond,
            incremental_field="_IngestionTime",
            db_incremental_field_last_value=datetime(2026, 10, 1, 22, 30, tzinfo=UTC),
        )

        assert result.raised is None
        assert [_window_end(query) for query in _queries(result.requests)] == [
            "2026-10-02T00:00:00Z",
            "2026-10-01T23:00:00Z",
            "2026-10-02T00:00:00Z",
            RUN_END,
        ]

    def test_empty_days_advance_the_window_without_rows(self) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {
                    TOKEN_PATH: [_token()],
                    QUERY_PATH: [_page([]), _page([]), _page([_row("2026-10-02T01:00:00Z", "z")])],
                }
            ),
            incremental_field="_IngestionTime",
            db_incremental_field_last_value=datetime(2026, 9, 30, 23, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert [_window_end(query) for query in _queries(result.requests)] == [
            "2026-10-01T00:00:00Z",
            "2026-10-02T00:00:00Z",
            RUN_END,
        ]
        assert _where_lines(_queries(result.requests)[0])[:2] == [
            "| where TimeGenerated >= datetime(2026-09-30T23:00:00.000000Z) - 3d",
            "| where ingestion_time() >= datetime(2026-09-30T23:00:00.000000Z)",
        ]
        assert [row["_ItemId"] for row in result.rows] == ["z"]

    @pytest.mark.parametrize(
        "inputs",
        [
            {},
            {
                "incremental_field": "_IngestionTime",
                "should_use_incremental_field": False,
                "db_incremental_field_last_value": datetime(2026, 10, 2, tzinfo=UTC),
            },
        ],
    )
    def test_full_refresh_starts_at_the_oldest_row_and_stops_on_an_empty_table(self, inputs: dict[str, Any]) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces", route({TOKEN_PATH: [_token()], QUERY_PATH: [_min_start("")]}), **inputs
        )

        assert result.raised is None
        assert _queries(result.requests) == [MIN_QUERY]
        assert result.rows == []

    def test_resume_starts_after_the_saved_row_and_ignores_the_watermark(self) -> None:
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route({TOKEN_PATH: [_token()], QUERY_PATH: [_page([_row("2026-10-02T11:00:00Z", "z")])]}),
            resume_state=AzureLogAnalyticsResumeConfig(ingested_at="2026-10-02T10:59:59.9999999Z", item_id="y"),
            incremental_field="_IngestionTime",
            db_incremental_field_last_value=datetime(2026, 10, 1, tzinfo=UTC),
        )

        assert result.raised is None
        (query,) = _queries(result.requests)
        assert "strcmp(_ItemId, 'y') > 0" in query
        assert "ingestion_time() >= datetime(" not in query

    def test_a_page_over_the_size_limit_is_read_again_smaller_then_the_size_resets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(azure_log_analytics, "PAGE_SIZE", 400)
        too_large = ScriptedResponse(
            json={
                "tables": [{"name": "PrimaryResult", "columns": COLUMNS, "rows": [_row("2026-10-01T22:10:00Z", "a")]}],
                "error": {
                    "code": "PartialError",
                    "message": "Query result set has exceeded the internal data size limit",
                },
            }
        )
        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run(
            "AppTraces",
            route(
                {
                    TOKEN_PATH: [_token()],
                    QUERY_PATH: [too_large, _page([_row("2026-10-01T22:10:00Z", "a")]), _page([]), _page([])],
                }
            ),
            incremental_field="_IngestionTime",
            db_incremental_field_last_value="2026-10-01T22:00:00Z",
        )

        assert result.raised is None
        queries = _queries(result.requests)
        assert [_take(query) for query in queries] == ["| take 400", "| take 200", "| take 400", "| take 400"]
        assert [_window_end(query) for query in queries] == [
            "2026-10-02T00:00:00Z",
            "2026-10-01T23:00:00Z",
            "2026-10-02T00:00:00Z",
            RUN_END,
        ]
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

    def test_a_dropped_connection_is_retried_within_the_budget(self) -> None:
        answers: Iterator[ScriptedResponse | BaseException] = iter(
            [ConnectionResetError(), _page([_row("2026-10-02T10:00:00Z", "a")])]
        )

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == TOKEN_PATH:
                return _token()
            answer = next(answers)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        result = SourceDriver(AzureLogAnalyticsSource(), _config()).run("AppTraces", respond, **WATERMARK_TODAY)

        assert result.raised is None
        assert len(_queries(result.requests)) == 2
        assert [row["_ItemId"] for row in result.rows] == ["a"]

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

    def test_meets_the_source_contract_on_an_incremental_table(self) -> None:
        def start(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any]]:
            inputs.incremental_field = "_IngestionTime"
            inputs.should_use_incremental_field = True
            inputs.db_incremental_field_last_value = datetime(2026, 9, 20, tzinfo=UTC)
            source = AzureLogAnalyticsSource()
            manager = source.get_resumable_source_manager(inputs)
            return source.source_for_pipeline(_config(), manager, inputs), manager

        verdict = check_extraction(start, ["AppTraces"])

        assert verdict.failed == frozenset()
        assert verdict.safe_point_exercised


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
            AzureLogAnalyticsResumeConfig(ingested_at="2026-10-01) | union X", item_id="a"),
            AzureLogAnalyticsResumeConfig(ingested_at="2026-10-01T10:00:00Z", item_id="a') or true or ('"),
        ],
    )
    def test_rejects_a_resume_cursor_that_would_change_the_query(self, resume: AzureLogAnalyticsResumeConfig) -> None:
        with pytest.raises(ValueError):
            build_query("AppTraces", resume, "2026-10-02T00:00:00Z", 10)


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
            ok, message = AzureLogAnalyticsSource().validate_credentials(
                _config(tables=None), team_id=1, schema_name=table
            )

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
            ok, message = AzureLogAnalyticsSource().validate_credentials(_config(), team_id=1)

        assert ok is False
        assert message is not None and "Microsoft Entra ID" in message
        assert [request.path for request in network.requests_log] == [TOKEN_PATH]

    @pytest.mark.parametrize(
        ("answers", "expected_ok", "expected_fragment", "expected_probes"),
        [
            ([_missing("AppTrace"), _missing("MyEvents_CL")], False, "None of the listed tables exist", 2),
            (
                [
                    ScriptedResponse(status=400, json={"error": {"code": "BadArgumentError", "message": "Basic plan"}}),
                    ScriptedResponse(status=403, json={"error": {"code": "InsufficientAccessError", "message": "No"}}),
                ],
                False,
                "None of the listed tables can be read",
                2,
            ),
            ([_missing("AppTrace"), _page([])], True, None, 2),
            ([_page([])], True, None, 1),
        ],
    )
    def test_creation_needs_one_readable_listed_table(
        self, answers: list[ScriptedResponse], expected_ok: bool, expected_fragment: str | None, expected_probes: int
    ) -> None:
        with scripted_network(route({TOKEN_PATH: [_token(), _token()], QUERY_PATH: [_page([]), *answers]})) as network:
            ok, message = AzureLogAnalyticsSource().validate_credentials(
                _config(tables="AppTrace\nMyEvents_CL"), team_id=1
            )

        assert ok is expected_ok
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message
        queries = [request.json()["query"] for request in network.requests_log if request.path == QUERY_PATH]
        assert queries == ["print ok = 1", "AppTrace | take 0", "MyEvents_CL | take 0"][: 1 + expected_probes]

    def test_setup_probes_use_short_deadlines_and_no_retries(self) -> None:
        unavailable = ScriptedResponse(
            status=504, json={"error": {"code": "GatewayTimeout"}}, headers={"Retry-After": "1"}
        )
        with scripted_network(route({TOKEN_PATH: [_token()], QUERY_PATH: [unavailable]})) as network:
            ok, message = AzureLogAnalyticsSource().validate_credentials(_config(), team_id=1)

        assert ok is False
        assert message is not None and "Could not query the Log Analytics workspace" in message
        queries = [request for request in network.requests_log if request.path == QUERY_PATH]
        assert len(queries) == 1
        assert queries[0].read_timeout == 30

    @pytest.mark.parametrize(
        ("config", "schema_name"),
        [(_config(tables="AppTraces | union SecurityEvent"), None), (_config(), "AppTraces | union SecurityEvent")],
    )
    def test_rejects_a_table_name_that_would_change_the_query_without_a_request(
        self, config: AzureLogAnalyticsSourceConfig, schema_name: str | None
    ) -> None:
        with scripted_network([]) as network:
            ok, message = AzureLogAnalyticsSource().validate_credentials(config, team_id=1, schema_name=schema_name)

        assert ok is False
        assert message is not None and "not a valid Log Analytics table name" in message
        assert network.requests_log == []


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
            if query.startswith("Missing_CL"):
                return ScriptedResponse(
                    status=400,
                    json={
                        "error": {
                            "code": "BadArgumentError",
                            "message": "The request had some invalid properties",
                            "innererror": {
                                "code": "SemanticError",
                                "message": "'take' operator: Failed to resolve table or column expression named 'Missing_CL'",
                            },
                        }
                    },
                )
            if query.startswith("Restricted"):
                return ScriptedResponse(
                    status=403, json={"error": {"code": "InsufficientAccessError", "message": "Insufficient access"}}
                )
            if query.startswith("Throttled"):
                return ScriptedResponse(status=429, json={}, headers={"Retry-After": "300"})
            return _page([])

        with scripted_network(respond) as network:
            permissions = AzureLogAnalyticsSource().get_endpoint_permissions(
                _config(),
                team_id=1,
                endpoints=["AppTraces", "BasicLogs_CL", "Missing_CL", "Restricted", "Throttled", "Later_CL"],
            )

        assert permissions["AppTraces"] is None
        assert permissions["BasicLogs_CL"] is not None and "Basic and Auxiliary" in permissions["BasicLogs_CL"]
        assert permissions["Missing_CL"] is not None and "doesn't exist in the workspace" in permissions["Missing_CL"]
        assert permissions["Restricted"] is not None and "can't read this table" in permissions["Restricted"]
        # A throttle counts as readable and ends probing, without retries, so setup stays fast.
        assert permissions["Throttled"] is None and permissions["Later_CL"] is None
        probed = [r.json()["query"].split(" ")[0] for r in network.requests_log if r.path == QUERY_PATH]
        assert probed == ["AppTraces", "BasicLogs_CL", "Missing_CL", "Restricted", "Throttled"]
