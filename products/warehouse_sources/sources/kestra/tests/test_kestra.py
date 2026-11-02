import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kestra import (
    KestraAuthMethodConfig,
    KestraSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.kestra import (
    KestraResumeState,
    kestra_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.source import KestraSource


@pytest.fixture
def config() -> KestraSourceConfig:
    return KestraSourceConfig(
        host="https://kestra.example.com/",
        tenant="main",
        auth_method=KestraAuthMethodConfig(selection="token", api_token="test-token"),
    )


@pytest.fixture(autouse=True)
def public_host() -> Iterator[MagicMock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid",
        return_value=(True, None),
    ) as validator:
        yield validator


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="executions",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=True,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field="start_date",
        incremental_field_type=None,
        job_id="job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = False
    return manager


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://kestra.example.com/api/v1/main/flows/search"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


@pytest.mark.parametrize("auth", ["token", "basic"])
@pytest.mark.parametrize(
    "incremental,watermark",
    [
        (True, datetime(2026, 1, 1, tzinfo=UTC)),
        (True, "2026-01-01T00:00:00+00:00"),
        (True, None),
        (False, datetime(2026, 1, 1, tzinfo=UTC)),
    ],
)
def test_execution_requests_and_terminal_page(
    config: KestraSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    auth: str,
    incremental: bool,
    watermark: datetime | str | None,
) -> None:
    if auth == "basic":
        config.auth_method = KestraAuthMethodConfig(selection="basic", username="user", password="pass")
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = watermark
    rows = [
        {"id": "run-1", "state": {"startDate": "2026-01-01T01:00:00.123456789Z"}},
        {"id": "run-2", "state": {"startDate": "2026-01-02T01:00:00Z"}},
    ]
    with patch(
        "requests.sessions.Session.send",
        side_effect=[
            response({"results": [rows[0]], "total": 101}),
            response({"results": [rows[1]], "total": 101}),
        ],
    ) as send:
        source = kestra_source(config, inputs, manager)
        pages = list(cast(Iterable[list[dict[str, Any]]], source.items()))
    assert [row["id"] for page in pages for row in page] == ["run-1", "run-2"]
    assert pages[0][0]["start_date"] == datetime(2026, 1, 1, 1, 0, 0, 123456, tzinfo=UTC)
    assert source.sort_mode == "asc"
    assert send.call_count == 2
    end_dates = []
    for index, call in enumerate(send.call_args_list, start=1):
        request: PreparedRequest = call.args[0]
        assert urlsplit(request.url or "").path == "/api/v1/main/executions/search"
        assert request.headers["Authorization"] == ("Bearer test-token" if auth == "token" else "Basic dXNlcjpwYXNz")
        params = parse_qs(urlsplit(request.url or "").query)
        assert params["page"] == [str(index)]
        assert params["size"] == ["100"]
        assert params["sort"] == ["state.startDate:asc"]
        assert params["dateFilter"] == ["START_DATE"]
        if incremental and watermark is not None:
            assert params["filters[startDate][GREATER_THAN_OR_EQUAL_TO]"] == ["2026-01-01T00:00:00+00:00"]
        else:
            assert "filters[startDate][GREATER_THAN_OR_EQUAL_TO]" not in params
        end_dates.append(params["filters[endDate][LESS_THAN_OR_EQUAL_TO]"])
        assert call.kwargs == {"allow_redirects": False, "timeout": (10, 60)}
    assert end_dates[0] == end_dates[1]
    assert [call.args[0].page for call in manager.save_state.call_args_list] == [2]
    manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize(
    "schema,rows,keys",
    [
        ("flows", [{"namespace": "a", "id": "same"}, {"namespace": "b", "id": "same"}], ["namespace", "id"]),
        (
            "triggers",
            [
                {"trigger": {"id": "same"}, "state": {"namespace": "a", "flowId": "flow-a", "triggerId": "same"}},
                {"trigger": {"id": "same"}, "state": {"namespace": "a", "flowId": "flow-b", "triggerId": "same"}},
            ],
            ["namespace", "flow_id", "trigger_id"],
        ),
    ],
)
def test_catalog_rows_keep_unique_keys(
    config: KestraSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    schema: str,
    rows: list[dict[str, Any]],
    keys: list[str],
) -> None:
    inputs.schema_name = schema
    inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)
    with patch(
        "requests.sessions.Session.send",
        side_effect=[
            response({"results": rows, "total": 2}),
            response({"results": [], "total": 2}),
        ],
    ) as send:
        source = kestra_source(config, inputs, manager)
        result = [row for page in cast(Iterable[list[dict[str, Any]]], source.items()) for row in page]
    assert source.primary_keys == keys
    assert len({tuple(row[key] for key in keys) for row in result}) == 2
    for call in send.call_args_list:
        request = call.args[0]
        assert urlsplit(request.url or "").path == f"/api/v1/main/{schema}/search"
        assert not any(key.startswith("filters[") for key in parse_qs(urlsplit(request.url or "").query))


@pytest.mark.parametrize(
    "status,schema,valid,message,probed",
    [
        (200, None, True, None, "flows"),
        (200, "executions", True, None, "executions"),
        (200, "logs", True, None, "logs"),
        (200, "task_runs", True, None, "executions"),
        (200, "execution_metrics", True, None, "executions"),
        (200, "flow_revisions", True, None, "flows"),
        (401, None, False, "Kestra rejected", "flows"),
        (401, "executions", False, "Kestra rejected", "executions"),
        (403, None, True, None, "flows"),
        (403, "executions", False, "Grant read permission", "executions"),
        (403, "flow_revisions", False, "Grant read permission", "flows"),
    ],
)
def test_credential_probe(
    config: KestraSourceConfig,
    status: int,
    schema: str | None,
    valid: bool,
    message: str | None,
    probed: str,
) -> None:
    with patch("requests.sessions.Session.send", return_value=response({"results": [], "total": 0}, status)) as send:
        success, error = validate_credentials(config, 1, schema)
    assert success == valid
    assert (message in error) if message and error else error is None
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer test-token"
    assert parse_qs(urlsplit(request.url or "").query) == {"page": ["1"], "size": ["1"]}
    assert urlsplit(request.url or "").path == f"/api/v1/main/{probed}/search"


@pytest.mark.parametrize("status", [400, 404])
def test_probe_does_not_hide_other_errors(config: KestraSourceConfig, status: int) -> None:
    with patch("requests.sessions.Session.send", return_value=response({}, status)) as send:
        with pytest.raises(HTTPError):
            validate_credentials(config, 1, None)
    send.assert_called_once()


@pytest.mark.parametrize("status", [401, 403])
def test_sync_errors_match_non_retryable_messages(
    config: KestraSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
) -> None:
    with patch("requests.sessions.Session.send", return_value=response({}, status)) as send:
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], kestra_source(config, inputs, manager).items()))
    assert any(pattern in str(error.value) for pattern in KestraSource().get_non_retryable_errors())
    send.assert_called_once()


@pytest.mark.parametrize("body", [{"unexpected": []}, {"results": "invalid"}])
def test_malformed_response_does_not_erase_table(
    config: KestraSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    body: object,
) -> None:
    with patch("requests.sessions.Session.send", return_value=response(body)):
        with pytest.raises(ValueError):
            list(cast(Iterable[Any], kestra_source(config, inputs, manager).items()))
    manager.clear_state.assert_not_called()


@pytest.mark.parametrize(
    "host",
    [
        "http://kestra.example.com",
        "https://user:pass@kestra.example.com",
        "https://kestra.example.com/api/v1",
        "https://kestra.example.com?q=x",
        "https://kestra.example.com#x",
        "https://kestra.example.com:bad",
        "https://[",
    ],
)
def test_invalid_origin_never_sends_credentials(config: KestraSourceConfig, host: str) -> None:
    config.host = host
    with patch("requests.sessions.Session.send") as send:
        valid, error = validate_credentials(config, 1, None)
    assert not valid
    assert error and "HTTPS origin" in error
    send.assert_not_called()


def test_private_host_blocks_probe_and_sync(
    config: KestraSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    public_host: MagicMock,
) -> None:
    public_host.return_value = (False, "private address")
    with patch("requests.sessions.Session.send") as send:
        valid, error = validate_credentials(config, 1, None)
        with pytest.raises(ValueError, match="public address"):
            kestra_source(config, inputs, manager)
    assert not valid
    assert error and "public address" in error
    send.assert_not_called()


@pytest.mark.parametrize("tenant", ["../main", "main/path", "", "main?x=y"])
def test_tenant_cannot_change_api_path(config: KestraSourceConfig, tenant: str) -> None:
    config.tenant = tenant
    with patch("requests.sessions.Session.send") as send:
        valid, error = validate_credentials(config, 1, None)
    assert not valid
    assert error and "tenant ID" in error
    send.assert_not_called()


@pytest.mark.parametrize(
    "auth,authorization,error_message",
    [
        ({"selection": "token", "api_token": "test-token"}, "Bearer test-token", None),
        ({"selection": "basic", "username": "user", "password": "pass"}, "Basic dXNlcjpwYXNz", None),
        ({"selection": "token"}, None, "Enter an API token."),
        ({"selection": "basic", "username": "user"}, None, "Enter a username and password."),
        ({"selection": "basic", "password": "pass"}, None, "Enter a username and password."),
    ],
)
def test_selected_auth_parses_and_validates(
    auth: dict[str, str], authorization: str | None, error_message: str | None
) -> None:
    config = KestraSourceConfig.from_dict({"host": "https://kestra.example.com", "tenant": "main", "auth_method": auth})
    if auth["selection"] == "token":
        assert config.auth_method.username is None
        assert config.auth_method.password is None
    else:
        assert config.auth_method.api_token is None
    with patch("requests.sessions.Session.send") as send:
        if authorization:
            send.return_value = response({"results": [], "total": 0})
        valid, error = validate_credentials(config, 1, None)
    assert (valid, error) == (authorization is not None, error_message)
    if authorization:
        assert send.call_args.args[0].headers["Authorization"] == authorization
    else:
        send.assert_not_called()


def test_unknown_table_fails_before_request(
    config: KestraSourceConfig, inputs: SourceInputs, manager: MagicMock
) -> None:
    inputs.schema_name = "unknown"
    with patch("requests.sessions.Session.send") as send:
        with pytest.raises(UnknownResourceError):
            kestra_source(config, inputs, manager)
        with pytest.raises(UnknownResourceError):
            validate_credentials(config, 1, "unknown")
    send.assert_not_called()


def page(results: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return ScriptedResponse(json={"results": results, "total": total})


@pytest.mark.parametrize("watermark", [datetime(2026, 1, 1, tzinfo=UTC), None])
def test_task_runs_fan_out_over_windowed_executions(config: KestraSourceConfig, watermark: datetime | None) -> None:
    executions = [
        {"id": "run-1", "state": {"startDate": "2026-01-02T00:00:00Z"}},
        {"id": "gone", "state": {"startDate": "2026-01-03T00:00:00Z"}},
        {"id": "run-2", "state": {"startDate": "2026-01-04T00:00:00Z"}},
    ]
    script = route(
        {
            "/api/v1/main/executions/search": [page(executions, 3)],
            "/api/v1/main/executions/run-1": [
                ScriptedResponse(
                    json={"id": "run-1", "taskRunList": [{"id": "tr-1", "executionId": "run-1", "taskId": "a"}]}
                )
            ],
            "/api/v1/main/executions/gone": [ScriptedResponse(status=404, json={"message": "Not found"})],
            "/api/v1/main/executions/run-2": [ScriptedResponse(json={"id": "run-2", "taskRunList": None})],
        }
    )
    result = SourceDriver(KestraSource(), config).run(
        "task_runs",
        script,
        incremental_field="execution_start_date",
        db_incremental_field_last_value=watermark,
    )
    assert result.raised is None
    assert result.rows == [
        {
            "id": "tr-1",
            "executionId": "run-1",
            "taskId": "a",
            "execution_start_date": datetime(2026, 1, 2, tzinfo=UTC),
        }
    ]
    search = result.requests[0]
    assert search.param("sort") == "state.startDate:asc"
    assert search.param("dateFilter") == "START_DATE"
    assert search.param("filters[startDate][GREATER_THAN_OR_EQUAL_TO]") == (watermark and watermark.isoformat())
    assert search.param("filters[endDate][LESS_THAN_OR_EQUAL_TO]") is not None
    assert all(request.param("size") is None for request in result.requests[1:])
    assert result.response is not None and result.response.sort_mode == "asc"


def test_execution_metrics_walk_pages_and_key_each_entry(config: KestraSourceConfig) -> None:
    metric = {"namespace": "ns", "flowId": "f", "executionId": "run-1", "type": "counter", "name": "rows", "value": 5.0}
    script = route(
        {
            "/api/v1/main/executions/search": [
                page([{"id": "run-1", "state": {"startDate": "2026-01-02T00:00:00Z"}}], 1)
            ],
            "/api/v1/main/metrics/run-1": [
                page([{**metric, "timestamp": "2026-01-02T00:00:01Z"}], 1001),
                page([{**metric, "timestamp": "2026-01-02T00:00:02Z"}, {**metric, "tags": {"k": "v"}}], 1001),
            ],
        }
    )
    result = SourceDriver(KestraSource(), config).run(
        "execution_metrics", script, incremental_field="execution_start_date"
    )
    assert result.raised is None
    metric_requests = [request for request in result.requests if "/metrics/" in request.path]
    assert [(request.param("page"), request.param("size")) for request in metric_requests] == [
        ("1", "1000"),
        ("2", "1000"),
    ]
    assert len({row["entry_id"] for row in result.rows}) == 3
    assert {row["execution_start_date"] for row in result.rows} == {datetime(2026, 1, 2, tzinfo=UTC)}
    assert not any(key.startswith("_executions") for row in result.rows for key in row)


def test_flow_revisions_bind_namespace_and_id(config: KestraSourceConfig) -> None:
    flows = [{"namespace": "company.team", "id": "etl"}, {"namespace": "company.team", "id": "deleted"}]
    script = route(
        {
            "/api/v1/main/flows/search": [page(flows, 2)],
            "/api/v1/main/flows/company.team/etl/revisions": [
                ScriptedResponse(
                    json=[
                        {"namespace": "company.team", "id": "etl", "revision": 1},
                        {"namespace": "company.team", "id": "etl", "revision": 2},
                    ]
                )
            ],
            "/api/v1/main/flows/company.team/deleted/revisions": [ScriptedResponse(status=404, json={})],
        }
    )
    result = SourceDriver(KestraSource(), config).run("flow_revisions", script)
    assert result.raised is None
    assert [row["revision"] for row in result.rows] == [1, 2]
    assert result.requests[0].query["sort"] == ("namespace:asc", "id:asc")


@pytest.mark.parametrize(
    "answers,expected_pages,expected_cursors",
    [
        (
            [
                {"type": "OFFSET", "total": 1001, "results": [{"message": "first"}]},
                {"type": "OFFSET", "total": 1001, "results": [{"message": "second"}]},
            ],
            ["1", "2"],
            [None, None],
        ),
        (
            [
                {"type": "CURSOR", "nextCursor": "c2", "results": [{"message": "first"}]},
                {"type": "CURSOR", "results": [{"message": "second"}]},
            ],
            ["1", None],
            [None, "c2"],
        ),
    ],
)
def test_logs_walk_offset_and_cursor_pages(
    config: KestraSourceConfig,
    answers: list[dict[str, Any]],
    expected_pages: list[str | None],
    expected_cursors: list[str | None],
) -> None:
    for answer in answers:
        for row in answer["results"]:
            row.update({"namespace": "ns", "flowId": "f", "timestamp": "2026-01-02T03:04:05.123456789Z"})
    result = SourceDriver(KestraSource(), config).run(
        "logs",
        [ScriptedResponse(json=answer) for answer in answers],
        incremental_field="timestamp",
        db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.raised is None
    assert result.params("page") == expected_pages
    assert result.params("cursor") == expected_cursors
    assert result.params("sort") == ["timestamp:asc", "timestamp:asc"]
    assert result.params("filters[startDate][GREATER_THAN_OR_EQUAL_TO]") == ["2026-01-01T00:00:00+00:00"] * 2
    assert [row["message"] for row in result.rows] == ["first", "second"]
    assert result.rows[0]["timestamp"] == datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    assert len({row["entry_id"] for row in result.rows}) == 2
    assert len(result.committed_states) == 1
    assert result.completed_state is None


@pytest.mark.parametrize(
    "resume,expected_page,expected_cursor",
    [
        (KestraResumeState(page=3, start_date=None, end_date="2026-01-05T00:00:00+00:00"), "3", None),
        (KestraResumeState(page=1, start_date=None, end_date="2026-01-05T00:00:00+00:00", cursor="c9"), None, "c9"),
    ],
)
def test_logs_resume_from_saved_page_or_cursor(
    config: KestraSourceConfig, resume: KestraResumeState, expected_page: str | None, expected_cursor: str | None
) -> None:
    result = SourceDriver(KestraSource(), config).run(
        "logs",
        [ScriptedResponse(json={"type": "OFFSET", "total": 0, "results": []})],
        incremental_field="timestamp",
        resume_state=resume,
    )
    assert result.raised is None
    assert result.params("page") == [expected_page]
    assert result.params("cursor") == [expected_cursor]
    assert result.params("filters[endDate][LESS_THAN_OR_EQUAL_TO]") == ["2026-01-05T00:00:00+00:00"]


def test_logs_stop_on_a_repeated_cursor(config: KestraSourceConfig) -> None:
    answer = {"type": "CURSOR", "nextCursor": "same", "results": []}
    result = SourceDriver(KestraSource(), config).run(
        "logs", [ScriptedResponse(json=answer), ScriptedResponse(json=answer)], incremental_field="timestamp"
    )
    assert isinstance(result.raised, ValueError)
    assert "same log cursor" in str(result.raised)
