from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.braintrust import (
    BraintrustResumeConfig,
    braintrust_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintrust.source import BraintrustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.braintrust import (
    BraintrustSourceConfig,
)

API_URL = "https://api.braintrust.dev"
HOST_CHECK = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid"


@pytest.fixture
def http() -> Iterator[responses.RequestsMock]:
    with (
        responses.RequestsMock() as mock,
        patch(HOST_CHECK, return_value=(True, None)),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.stop",
            return_value=True,
        ),
    ):
        yield mock


def make_config(api_url: str = API_URL, api_key: str = "fake-braintrust-key") -> BraintrustSourceConfig:
    return BraintrustSourceConfig(api_key=api_key, api_url=api_url)


def make_manager(cursor: str | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = cursor is not None
    manager.load_state.return_value = BraintrustResumeConfig(cursor=cursor) if cursor else None
    return manager


@pytest.mark.parametrize(
    ("table", "path"),
    [
        ("projects", "project"),
        ("experiments", "experiment"),
        ("datasets", "dataset"),
        ("prompts", "prompt"),
        ("functions", "function"),
    ],
)
def test_pagination_auth_and_checkpoints(http: responses.RequestsMock, table: str, path: str) -> None:
    url = f"{API_URL}/v1/{path}"
    http.get(url, json={"objects": [{"id": "new"}, {"id": "middle"}]})
    http.get(url, json={"objects": [{"id": "old"}]})
    http.get(url, json={"objects": []})
    manager = make_manager()
    result = braintrust_source(make_config(), table, 123, "job", manager)
    pages = iter(cast(Iterable[Any], result.items()))
    assert next(pages) == [{"id": "new"}, {"id": "middle"}]
    assert list(pages) == [[{"id": "old"}]]
    assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["middle", "old"]
    assert [parse_qs(urlsplit(call.request.url).query) for call in http.calls] == [
        {"limit": ["100"]},
        {"limit": ["100"], "starting_after": ["middle"]},
        {"limit": ["100"], "starting_after": ["old"]},
    ]
    assert all(call.request.headers["Authorization"] == "Bearer fake-braintrust-key" for call in http.calls)
    assert result.on_complete is not None
    result.on_complete()
    manager.clear_state.assert_called_once_with()


@pytest.mark.parametrize("cursor", [None, "saved"])
def test_empty_page_and_resume(http: responses.RequestsMock, cursor: str | None) -> None:
    http.get(f"{API_URL}/v1/project", json={"objects": []})
    manager = make_manager(cursor)
    result = braintrust_source(make_config(), "projects", 123, "job", manager)
    assert list(cast(Iterable[Any], result.items())) == []
    expected = {"limit": ["100"]}
    if cursor:
        expected["starting_after"] = [cursor]
    assert parse_qs(urlsplit(http.calls[0].request.url).query) == expected
    manager.save_state.assert_not_called()
    assert len(http.calls) == 1


@pytest.mark.parametrize("resumed", [False, True])
def test_repeated_cursor_fails(http: responses.RequestsMock, resumed: bool) -> None:
    http.get(f"{API_URL}/v1/project", json={"objects": [{"id": "same"}]})
    result = braintrust_source(make_config(), "projects", 123, "job", make_manager("same" if resumed else None))
    with pytest.raises(ValueError, match="not advancing"):
        list(cast(Iterable[Any], result.items()))
    assert len(http.calls) == (1 if resumed else 2)


@pytest.mark.parametrize("body", [{}, {"objects": None}, {"error": "unexpected"}])
def test_malformed_page_does_not_succeed(http: responses.RequestsMock, body: dict[str, Any]) -> None:
    http.get(f"{API_URL}/v1/project", json=body)
    result = braintrust_source(make_config(), "projects", 123, "job", make_manager())
    with pytest.raises(RESTClientRetryableError):
        list(cast(Iterable[Any], result.items()))


@pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500])
def test_credentials_and_error_classification(http: responses.RequestsMock, status: int) -> None:
    http.get(f"{API_URL}/v1/project", json={"objects": []}, status=status)
    if status in (429, 500):
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(make_config(), 123)
    elif status == 404:
        with pytest.raises(HTTPError):
            validate_credentials(make_config(), 123)
    else:
        valid, message = validate_credentials(make_config(), 123)
        assert valid is (status == 200)
        if status == 401:
            assert message and "rejected the API key" in message
        elif status == 403:
            assert message and "permissions" in message
        else:
            assert message is None
    assert parse_qs(urlsplit(http.calls[0].request.url).query) == {"limit": ["1"]}
    if status < 429:
        assert len(http.calls) == 1
    assert http.calls[0].request.headers["Authorization"] == "Bearer fake-braintrust-key"


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_match_non_retryable_messages(http: responses.RequestsMock, status: int) -> None:
    http.get(f"{API_URL}/v1/project", status=status)
    result = braintrust_source(make_config(), "projects", 123, "job", make_manager())
    with pytest.raises(HTTPError) as error:
        list(cast(Iterable[Any], result.items()))
    messages = [
        message
        for pattern, message in BraintrustSource().get_non_retryable_errors().items()
        if pattern in str(error.value)
    ]
    assert len(messages) == 1
    assert messages[0] and "API key" in messages[0]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://",
        "https://example.com/v1",
        "https://user:pass@example.com",
        "https://example.com?q=1",
        "https://example.com#fragment",
        "https://example.com:80",
        "https://example.com:bad",
        "https://[",
    ],
)
def test_invalid_urls_fail_before_http(http: responses.RequestsMock, url: str) -> None:
    valid, message = validate_credentials(make_config(api_url=url), 123)
    assert not valid
    assert message and "HTTPS API URL" in message
    assert len(http.calls) == 0


@pytest.mark.parametrize("api_url", ["https://api-eu.braintrust.dev/", "https://braintrust.example.com"])
def test_custom_hosts(http: responses.RequestsMock, api_url: str) -> None:
    http.get(f"{api_url.rstrip('/')}/v1/project", json={"objects": []})
    assert validate_credentials(make_config(api_url=api_url), 123) == (True, None)
    assert urlsplit(http.calls[0].request.url).hostname == urlsplit(api_url).hostname


def test_private_host_rejected_for_probe_and_sync(http: responses.RequestsMock) -> None:
    with patch(HOST_CHECK, return_value=(False, "private host")):
        valid, message = validate_credentials(make_config(), 123)
        assert not valid
        assert message and "public IP address" in message
        with pytest.raises(ValueError, match="public IP address"):
            braintrust_source(make_config(), "projects", 123, "job", make_manager())
    assert len(http.calls) == 0


def test_redirect_does_not_forward_credentials(http: responses.RequestsMock) -> None:
    http.get(f"{API_URL}/v1/project", status=302, headers={"Location": "https://other.example.com"})
    with pytest.raises(ValueError, match="refusing to follow"):
        validate_credentials(make_config(), 123)
    assert len(http.calls) == 1


def test_blank_key_does_not_accept_anonymous_access(http: responses.RequestsMock) -> None:
    valid, message = validate_credentials(make_config(api_key=" "), 123)
    assert not valid
    assert message and "API key" in message
    assert len(http.calls) == 0


def test_unknown_table_fails_before_http(http: responses.RequestsMock) -> None:
    with pytest.raises(UnknownResourceError):
        braintrust_source(make_config(), "unknown", 123, "job", make_manager())
    assert len(http.calls) == 0
