import json
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from typing import Any, cast
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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
def driver(config: HarnessSourceConfig) -> SourceDriver:
    return SourceDriver(HarnessSource(), config)


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
    config: HarnessSourceConfig, status: int, schema: str | None, valid: bool, message: str | None
) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json={"data": {"content": [], "totalPages": 0}})]
    ) as network:
        result, error = HarnessSource().validate_credentials(config, 1, schema)
    assert result is valid
    if message is None:
        assert error is None
    else:
        assert error is not None and message in error
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["x-api-key"] == "fake-token"
    assert request.param("size") == "1"
    assert request.path == ("/ng/api/servicesV2" if schema == "services" else "/pipeline/api/pipelines/list")


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal(driver: SourceDriver, status: int) -> None:
    result = driver.run("executions", [ScriptedResponse(status=status, json={})])
    assert isinstance(result.raised, HTTPError)
    assert any(pattern in str(result.raised) for pattern in HarnessSource().get_non_retryable_errors())
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_errors_propagate(config: HarnessSourceConfig, status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
        with pytest.raises(RESTClientRetryableError):
            HarnessSource().validate_credentials(config, 1)
    assert len(network.requests_log) == 5


@pytest.mark.parametrize("region", ["invalid", "https://example.com", "http://127.0.0.1", ""])
def test_invalid_region_never_sends_token(config: HarnessSourceConfig, region: str) -> None:
    config.region = cast(Any, region)
    with scripted_network([]) as network:
        assert HarnessSource().validate_credentials(config, 1) == (False, "Select a supported Harness region.")
    result = SourceDriver(HarnessSource(), config).run("services", [])
    assert isinstance(result.raised, ValueError)
    assert "supported Harness region" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


@pytest.mark.parametrize(
    ("name", "body", "error"),
    [
        ("pipelines", {"status": "ERROR"}, "Required data_selector"),
        ("pipelines", {"data": {"content": [{}]}}, "without an identifier"),
        ("services", {"data": {"content": [{"service": None}]}}, "without an identifier"),
        ("environments", {"data": {"content": [{"environment": {}}]}}, "without an identifier"),
    ],
)
def test_malformed_response_fails(driver: SourceDriver, name: str, body: dict[str, Any], error: str) -> None:
    result = driver.run(name, [ScriptedResponse(json=body)])
    assert isinstance(result.raised, ValueError)
    assert error in str(result.raised)
    assert result.saved_states == []


def test_unknown_table(driver: SourceDriver) -> None:
    result = driver.run("unknown", [])
    assert isinstance(result.raised, UnknownResourceError)
    assert result.requests == []
