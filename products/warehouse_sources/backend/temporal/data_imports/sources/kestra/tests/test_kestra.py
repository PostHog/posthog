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


def test_resume_preserves_query_window(config: KestraSourceConfig, inputs: SourceInputs, manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = KestraResumeState(
        page=4,
        start_date="2026-01-01T00:00:00+00:00",
        end_date="2026-01-03T00:00:00+00:00",
    )
    inputs.db_incremental_field_last_value = datetime(2026, 1, 2, tzinfo=UTC)
    with patch("requests.sessions.Session.send", return_value=response({"results": [], "total": 0})) as send:
        assert list(cast(Iterable[Any], kestra_source(config, inputs, manager).items())) == []
    params = parse_qs(urlsplit(send.call_args.args[0].url).query)
    assert params["page"] == ["4"]
    assert params["filters[startDate][GREATER_THAN_OR_EQUAL_TO]"] == ["2026-01-01T00:00:00+00:00"]
    assert params["filters[endDate][LESS_THAN_OR_EQUAL_TO]"] == ["2026-01-03T00:00:00+00:00"]
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (200, None, True, None),
        (200, "executions", True, None),
        (401, None, False, "Kestra rejected"),
        (401, "executions", False, "Kestra rejected"),
        (403, None, True, None),
        (403, "executions", False, "Grant read permission"),
    ],
)
def test_credential_probe(
    config: KestraSourceConfig,
    status: int,
    schema: str | None,
    valid: bool,
    message: str | None,
) -> None:
    with patch("requests.sessions.Session.send", return_value=response({"results": [], "total": 0}, status)) as send:
        success, error = validate_credentials(config, 1, schema)
    assert success == valid
    assert (message in error) if message and error else error is None
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer test-token"
    assert parse_qs(urlsplit(request.url or "").query) == {"page": ["1"], "size": ["1"]}
    assert urlsplit(request.url or "").path == f"/api/v1/main/{schema or 'flows'}/search"


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


def test_empty_trigger_page_does_not_end_sync(
    config: KestraSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
) -> None:
    inputs.schema_name = "triggers"
    row = {"trigger": {"id": "daily"}, "state": {"namespace": "demo", "flowId": "flow", "triggerId": "daily"}}
    with patch(
        "requests.sessions.Session.send",
        side_effect=[
            response({"results": [], "total": 101}),
            response({"results": [row], "total": 101}),
        ],
    ) as send:
        result = list(cast(Iterable[list[dict[str, Any]]], kestra_source(config, inputs, manager).items()))
    assert result[0][0]["trigger_id"] == "daily"
    assert send.call_count == 2
    assert manager.save_state.call_args.args[0].page == 2
