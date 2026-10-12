import json
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitec import (
    HumanitecSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.humanitec import (
    humanitec_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.source import HumanitecSource

BASE = "https://api.humanitec.io/orgs/example-org"
CONFIG = HumanitecSourceConfig(api_token="test-token", organization_id="example-org")


def source_items(source: SourceResponse) -> Iterable[list[dict[str, object]]]:
    return cast(Iterable[list[dict[str, object]]], source.items())


def response(body: object, status: int = 200, next_url: str | None = None) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    if next_url:
        result.headers["Link"] = f'<{next_url}>; rel="next"'
    return result


@pytest.fixture
def http() -> Iterator[MagicMock]:
    session = MagicMock()
    session.headers = {}
    session.prepare_request.side_effect = lambda request: request.prepare()
    session.responses = []

    def send(request: PreparedRequest, **kwargs: object) -> Response:
        result = session.responses.pop(0)
        result.url = request.url
        result.request = request
        return result

    session.send.side_effect = send
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
        return_value=session,
    ):
        yield session


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize(
    "endpoint,suffix,key", [("deployments", "deploys", "id"), ("active_resources", "resources", "gu_res_id")]
)
def test_environment_children_keep_parent_keys(
    http: MagicMock, manager: MagicMock, endpoint: str, suffix: str, key: str
) -> None:
    http.responses = [
        response(
            [
                {"id": "app-a", "envs": [{"id": "staging"}, {"id": "production"}]},
                {"id": "empty-app", "envs": []},
                {"id": "app-b", "envs": [{"id": "staging"}]},
            ]
        ),
        response([{key: "same-id", "env_id": "staging"}]),
        response([]),
        response([{key: "same-id", "env_id": "staging"}]),
    ]
    source = humanitec_source(CONFIG, endpoint, 1, "job", manager)
    rows = [row for page in source_items(source) for row in page]
    assert rows == [
        {key: "same-id", "app_id": "app-a", "env_id": "staging"},
        {key: "same-id", "app_id": "app-b", "env_id": "staging"},
    ]
    assert len({tuple(row[field] for field in source.primary_keys or []) for row in rows}) == 2
    assert [call.args[0].url for call in http.send.call_args_list] == [
        f"{BASE}/apps",
        f"{BASE}/apps/app-a/envs/staging/{suffix}",
        f"{BASE}/apps/app-a/envs/production/{suffix}",
        f"{BASE}/apps/app-b/envs/staging/{suffix}",
    ]


@pytest.mark.parametrize(
    "status,expected", [(200, None), (401, "rejected the API token"), (403, "cannot read"), (404, "could not find")]
)
def test_credential_probe(http: MagicMock, status: int, expected: str | None) -> None:
    http.responses = [
        response(
            {"id": "example-org"}
            if status == 200
            else {"error": f"HTTP-{status}", "message": HTTPStatus(status).phrase},
            status,
        )
    ]
    valid, error = validate_credentials(CONFIG)
    assert valid is (status == 200)
    assert (error is None) if expected is None else expected in cast(str, error)
    http.send.assert_called_once()
    assert http.send.call_args.args[0].url == BASE
    assert http.send.call_args.args[0].headers["Authorization"] == "Bearer test-token"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_are_terminal(http: MagicMock, manager: MagicMock, status: int) -> None:
    http.responses = [response({"error": f"HTTP-{status}", "message": HTTPStatus(status).phrase}, status)]
    source = humanitec_source(CONFIG, "applications", 1, "job", manager)
    with pytest.raises(HTTPError) as error:
        list(source_items(source))
    assert any(pattern in str(error.value) for pattern in HumanitecSource().get_non_retryable_errors())
    http.send.assert_called_once()


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_errors_propagate(http: MagicMock, status: int) -> None:
    http.responses = [response({"error": f"HTTP-{status}"}, status)]
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.DEFAULT_RETRY_ATTEMPTS", 1
    ):
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(CONFIG)
    http.send.assert_called_once()


@pytest.mark.parametrize(
    "organization",
    ["", "../users", "example/org", "https://example.com", "UPPERCASE", "bad--id", "a" * 49 + "!", "a" * 51],
)
def test_invalid_organization_never_sends_token(http: MagicMock, manager: MagicMock, organization: str) -> None:
    config = HumanitecSourceConfig(api_token="test-token", organization_id=organization)
    valid, error = validate_credentials(config)
    assert not valid
    assert error and "organization ID" in error
    with pytest.raises(ValueError, match="organization ID"):
        humanitec_source(config, "applications", 1, "job", manager)
    http.send.assert_not_called()


@pytest.mark.parametrize(
    "next_url", ["https://example.com/steal", "http://api.humanitec.io/orgs/example-org/apps/app-a/pipelines"]
)
def test_pipeline_links_cannot_retarget_credentials(http: MagicMock, manager: MagicMock, next_url: str) -> None:
    http.responses = [response([{"id": "app-a"}]), response([{"id": "first"}], next_url=next_url)]
    source = humanitec_source(CONFIG, "pipelines", 1, "job", manager)
    with pytest.raises(ValueError, match="Refusing to send"):
        list(source_items(source))
    assert http.send.call_count == 2


def test_unknown_table(http: MagicMock, manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        humanitec_source(CONFIG, "missing", 1, "job", manager)
    http.send.assert_not_called()


def test_unexpected_probe_error_is_not_reported_as_invalid_credentials(http: MagicMock) -> None:
    http.responses = [response({"error": "HTTP-400"}, 400)]
    with pytest.raises(HTTPError):
        validate_credentials(CONFIG)
    http.send.assert_called_once()
