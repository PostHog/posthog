import json
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harness import (
    HarnessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harness.harness import (
    HarnessResumeConfig,
    harness_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harness.source import HarnessSource

SESSION_FACTORY = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


@pytest.fixture
def config() -> HarnessSourceConfig:
    return HarnessSourceConfig(
        api_key="fake-token", account_id="example-account", organization_id="example-org", project_id="example-project"
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with patch(SESSION_FACTORY) as factory:
        session = factory.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request.prepare()
        yield session


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://app.harness.io/pipeline/api/pipelines/list"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.mark.parametrize(
    ("name", "path", "method", "body", "row", "expected"),
    [
        (
            "pipelines",
            "/pipeline/api/pipelines/list",
            "POST",
            {"filterType": "PipelineSetup"},
            {"identifier": "build", "createdAt": 100},
            {"identifier": "build", "createdAt": 100},
        ),
        (
            "executions",
            "/pipeline/api/pipelines/execution/summary",
            "POST",
            {"filterType": "PipelineExecution"},
            {"planExecutionId": "run-1", "status": "Running"},
            {"planExecutionId": "run-1", "status": "Running"},
        ),
        (
            "services",
            "/ng/api/servicesV2",
            "GET",
            None,
            {"service": {"identifier": "web"}, "createdAt": 100, "lastModifiedAt": 200},
            {"identifier": "web", "createdAt": 100, "lastModifiedAt": 200},
        ),
        (
            "environments",
            "/ng/api/environmentsV2",
            "GET",
            None,
            {"environment": {"identifier": "production", "type": "Production"}, "createdAt": 100},
            {"identifier": "production", "type": "Production", "createdAt": 100},
        ),
    ],
)
def test_requests_and_pagination(
    config: HarnessSourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    name: str,
    path: str,
    method: str,
    body: dict[str, str] | None,
    row: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    transport.send.side_effect = [
        response({"data": {"content": [row], "totalPages": 2}}),
        response({"data": {"content": [row], "totalPages": 2}}),
    ]
    source = harness_source(config, name, 1, "job", manager)
    assert list(items(source)) == [[expected], [expected]]
    assert transport.send.call_count == 2
    for page, call in enumerate(transport.send.call_args_list):
        request = call.args[0]
        assert urlsplit(request.url).path == path
        assert request.method == method
        assert request.headers["x-api-key"] == "fake-token"
        assert parse_qs(urlsplit(request.url).query) == {
            "accountIdentifier": ["example-account"],
            "orgIdentifier": ["example-org"],
            "projectIdentifier": ["example-project"],
            "size": ["100"],
            "page": [str(page)],
        }
        assert (json.loads(request.body) if request.body else None) == body
        assert call.kwargs["allow_redirects"] is False
    manager.save_state.assert_called_once_with(HarnessResumeConfig(page=1))
    manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize("has_saved_state", [True, False])
def test_resume_from_saved_page(
    config: HarnessSourceConfig, manager: MagicMock, transport: MagicMock, has_saved_state: bool
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = HarnessResumeConfig(page=4) if has_saved_state else None
    transport.send.return_value = response(
        {"data": {"content": [{"identifier": "last"}], "totalPages": 5 if has_saved_state else 1}}
    )
    assert list(items(harness_source(config, "pipelines", 1, "job", manager))) == [[{"identifier": "last"}]]
    query = parse_qs(urlsplit(transport.send.call_args.args[0].url).query)
    assert query["page"] == ["4" if has_saved_state else "0"]
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("total_pages", [0, 3, None])
def test_empty_terminal_page(
    config: HarnessSourceConfig, manager: MagicMock, transport: MagicMock, total_pages: int | None
) -> None:
    data: dict[str, Any] = {"content": []}
    if total_pages is not None:
        data["totalPages"] = total_pages
    transport.send.return_value = response({"data": data})
    assert list(items(harness_source(config, "pipelines", 1, "job", manager))) == []
    transport.send.assert_called_once()
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    ("status", "schema", "valid", "message"),
    [
        (200, None, True, None),
        (401, None, False, "rejected your API key"),
        (403, None, True, None),
        (403, "services", False, "view permission"),
        (400, None, False, "account, organization, project, and region"),
        (404, None, False, "account, organization, project, and region"),
    ],
)
def test_credential_probe(
    config: HarnessSourceConfig, transport: MagicMock, status: int, schema: str | None, valid: bool, message: str | None
) -> None:
    transport.send.return_value = response({"data": {"content": [], "totalPages": 0}}, status)
    result, error = HarnessSource().validate_credentials(config, 1, schema)
    assert result is valid
    if message is None:
        assert error is None
    else:
        assert error is not None and message in error
    transport.send.assert_called_once()
    request = transport.send.call_args.args[0]
    assert request.headers["x-api-key"] == "fake-token"
    assert parse_qs(urlsplit(request.url).query)["size"] == ["1"]
    assert urlsplit(request.url).path == (
        "/ng/api/servicesV2" if schema == "services" else "/pipeline/api/pipelines/list"
    )


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal(
    config: HarnessSourceConfig, manager: MagicMock, transport: MagicMock, status: int
) -> None:
    transport.send.return_value = response({}, status)
    with pytest.raises(HTTPError) as error:
        list(items(harness_source(config, "executions", 1, "job", manager)))
    assert any(pattern in str(error.value) for pattern in HarnessSource().get_non_retryable_errors())
    transport.send.assert_called_once()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_errors_propagate(config: HarnessSourceConfig, transport: MagicMock, status: int) -> None:
    transport.send.return_value = response({}, status)
    with patch("tenacity.nap.time.sleep"), pytest.raises(RESTClientRetryableError):
        HarnessSource().validate_credentials(config, 1)
    assert transport.send.call_count == 5


@pytest.mark.parametrize(
    ("region", "host"),
    [
        ("us", "app.harness.io"),
        ("us3", "app3.harness.io"),
        ("us_accounts", "accounts.harness.io"),
        ("eu", "accounts.eu.harness.io"),
    ],
)
def test_region_routes_requests(
    config: HarnessSourceConfig,
    manager: MagicMock,
    transport: MagicMock,
    region: Literal["us", "us3", "us_accounts", "eu"],
    host: str,
) -> None:
    config.region = region
    transport.send.return_value = response({"data": {"content": [], "totalPages": 0}})
    list(items(harness_source(config, "services", 1, "job", manager)))
    request = transport.send.call_args.args[0]
    assert urlsplit(request.url).hostname == host
    assert urlsplit(request.url).scheme == "https"


@pytest.mark.parametrize("region", ["invalid", "https://example.com", "http://127.0.0.1", ""])
def test_invalid_region_never_sends_token(
    config: HarnessSourceConfig, manager: MagicMock, transport: MagicMock, region: str
) -> None:
    config.region = cast(Any, region)
    assert HarnessSource().validate_credentials(config, 1) == (False, "Select a supported Harness region.")
    with pytest.raises(ValueError, match="supported Harness region"):
        harness_source(config, "services", 1, "job", manager)
    transport.send.assert_not_called()


@pytest.mark.parametrize(
    ("name", "body", "error"),
    [
        ("pipelines", {"status": "ERROR"}, "Required data_selector"),
        ("pipelines", {"data": {"content": [{}]}}, "without an identifier"),
        ("services", {"data": {"content": [{"service": None}]}}, "without an identifier"),
        ("environments", {"data": {"content": [{"environment": {}}]}}, "without an identifier"),
    ],
)
def test_malformed_response_fails(
    config: HarnessSourceConfig, manager: MagicMock, transport: MagicMock, name: str, body: dict[str, Any], error: str
) -> None:
    transport.send.return_value = response(body)
    with pytest.raises(ValueError, match=error):
        list(items(harness_source(config, name, 1, "job", manager)))
    manager.save_state.assert_not_called()


def test_unknown_table(config: HarnessSourceConfig, manager: MagicMock, transport: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        harness_source(config, "unknown", 1, "job", manager)
    transport.send.assert_not_called()
