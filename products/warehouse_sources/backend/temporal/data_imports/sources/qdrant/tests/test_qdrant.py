from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import Mock, patch

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qdrant import QdrantSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.qdrant import (
    QdrantResumeConfig,
    qdrant_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.source import QdrantSource

ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
ACCOUNTS_URL = "https://api.cloud.qdrant.io/api/account/v1/accounts"
CLUSTERS_URL = f"https://api.cloud.qdrant.io/api/cluster/v1/accounts/{ACCOUNT_ID}/clusters"


@pytest.fixture
def config() -> QdrantSourceConfig:
    return QdrantSourceConfig(api_key="fake-management-key", account_id=ACCOUNT_ID)


@pytest.fixture
def manager() -> Mock:
    result = Mock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def sync_items(response: SourceResponse) -> Iterable[Any]:
    items = response.items()
    assert isinstance(items, Iterable)
    return items


@pytest.mark.parametrize(
    "endpoint,path",
    [
        ("clusters", f"/api/cluster/v1/accounts/{ACCOUNT_ID}/clusters"),
        ("backups", f"/api/cluster/backup/v1/accounts/{ACCOUNT_ID}/backups"),
        ("backup_schedules", f"/api/cluster/backup/v1/accounts/{ACCOUNT_ID}/backup_schedules"),
        ("backup_restores", f"/api/cluster/backup/v1/accounts/{ACCOUNT_ID}/backup_restores"),
    ],
)
@pytest.mark.parametrize("terminal_token", [None, ""])
def test_paginated_full_refresh(
    config: QdrantSourceConfig, manager: Mock, endpoint: str, path: str, terminal_token: str | None
) -> None:
    first = {"id": "first", "createdAt": "2025-01-01T00:00:00Z", "accountId": ACCOUNT_ID}
    second = {"id": "second", "createdAt": "2025-02-01T00:00:00Z", "accountId": ACCOUNT_ID}
    terminal: dict[str, Any] = {"items": [second]}
    if terminal_token is not None:
        terminal["nextPageToken"] = terminal_token

    with requests_mock.Mocker() as http:
        http.get(
            f"https://api.cloud.qdrant.io{path}",
            [
                {"json": {"items": [first], "nextPageToken": "next+/="}},
                {"json": terminal},
            ],
        )
        response = qdrant_source(config, endpoint, 1, "job", manager)
        pages = iter(sync_items(response))
        assert next(pages) == [first]
        manager.save_state.assert_not_called()
        assert next(pages) == [second]
        manager.save_state.assert_called_once_with(QdrantResumeConfig(cursor="next+/="))
        assert list(pages) == []
        assert http.call_count == 2
        manager.save_state.assert_called_once()
        assert [parse_qs(urlsplit(request.url).query) for request in http.request_history] == [
            {"pageSize": ["100"]},
            {"pageSize": ["100"], "pageToken": ["next+/="]},
        ]
        assert all(request.headers["Authorization"] == "apikey fake-management-key" for request in http.request_history)
        assert all(request.method == "GET" for request in http.request_history)
        assert response.name == endpoint
        assert response.on_complete is not None
        response.on_complete()
        manager.clear_state.assert_called_once_with()


@pytest.mark.parametrize("resume", [None, QdrantResumeConfig(cursor="saved-token")])
@pytest.mark.parametrize("body", [{"items": []}, {}, {"items": [], "nextPageToken": ""}])
def test_resume_and_empty_terminal_page(
    config: QdrantSourceConfig, manager: Mock, resume: QdrantResumeConfig | None, body: dict[str, Any]
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = resume
    with requests_mock.Mocker() as http:
        http.get(CLUSTERS_URL, json=body)
        assert list(sync_items(qdrant_source(config, "clusters", 1, "job", manager))) == []
        assert http.call_count == 1
        expected = {"pageSize": ["100"]}
        if resume:
            expected["pageToken"] = ["saved-token"]
        assert parse_qs(urlsplit(http.request_history[0].url).query) == expected
        manager.save_state.assert_not_called()


def test_empty_page_with_cursor_continues(config: QdrantSourceConfig, manager: Mock) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            CLUSTERS_URL,
            [
                {"json": {"items": [], "nextPageToken": "next"}},
                {"json": {"items": [{"id": "last"}]}},
            ],
        )
        assert list(sync_items(qdrant_source(config, "clusters", 1, "job", manager))) == [[{"id": "last"}]]
        assert http.call_count == 2
        manager.save_state.assert_called_once_with(QdrantResumeConfig(cursor="next"))


def test_repeated_cursor_fails(config: QdrantSourceConfig, manager: Mock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = QdrantResumeConfig(cursor="repeated")
    with requests_mock.Mocker() as http:
        http.get(CLUSTERS_URL, json={"items": [{"id": "first"}], "nextPageToken": "repeated"})
        with pytest.raises(ValueError, match="pagination is not advancing"):
            list(sync_items(qdrant_source(config, "clusters", 1, "job", manager)))
        assert http.call_count == 1


@pytest.mark.parametrize("schema_name", [None, "clusters", "backups", "backup_schedules", "backup_restores"])
def test_credentials_make_one_probe(config: QdrantSourceConfig, schema_name: str | None) -> None:
    with requests_mock.Mocker() as http:
        body: dict[str, Any]
        if schema_name is None:
            url = ACCOUNTS_URL
            body = {"items": [{"id": ACCOUNT_ID}]}
        else:
            service = "cluster" if schema_name == "clusters" else "cluster/backup"
            url = f"https://api.cloud.qdrant.io/api/{service}/v1/accounts/{ACCOUNT_ID}/{schema_name}"
            body = {"items": [], "nextPageToken": "unused"}
        http.get(url, json=body)
        assert validate_credentials(config, schema_name) == (True, None)
        assert http.call_count == 1
        request = http.request_history[0]
        assert request.headers["Authorization"] == "apikey fake-management-key"
        assert parse_qs(urlsplit(request.url).query) == ({"pageSize": ["1"]} if schema_name else {})


@pytest.mark.parametrize("body", [{"items": []}, {"items": [{"id": "another-account"}]}])
def test_credentials_reject_unavailable_account(config: QdrantSourceConfig, body: dict[str, Any]) -> None:
    with requests_mock.Mocker() as http:
        http.get(ACCOUNTS_URL, json=body)
        valid, message = validate_credentials(config)
        assert not valid
        assert message is not None and "cannot access this account" in message


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("account_id", "../another-account", "valid Qdrant account ID"),
        ("account_id", "https://example.com", "valid Qdrant account ID"),
        ("api_key", "", "Cloud Management Key"),
        ("api_key", "fake\r\nkey", "Cloud Management Key"),
        ("api_key", "fake\u200bkey", "Cloud Management Key"),
    ],
)
def test_invalid_credentials_do_not_send_requests(
    config: QdrantSourceConfig, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    with requests_mock.Mocker() as http:
        valid, error = validate_credentials(config)
        assert not valid
        assert error is not None and message in error
        assert not http.called


@pytest.mark.parametrize("status,expected", [(401, "Cloud Management Key"), (403, "permission"), (404, "account ID")])
def test_credentials_map_http_errors(config: QdrantSourceConfig, status: int, expected: str) -> None:
    with requests_mock.Mocker() as http:
        http.get(ACCOUNTS_URL, status_code=status, json={"code": status, "message": "authentication failed"})
        valid, message = validate_credentials(config)
        assert not valid
        assert message is not None and expected in message
        assert http.call_count == 1


@pytest.mark.parametrize("status", [400, 401, 403])
def test_sync_http_errors_are_not_retried(config: QdrantSourceConfig, manager: Mock, status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(CLUSTERS_URL, status_code=status, json={"code": status, "message": "authentication failed"})
        with pytest.raises(HTTPError) as error:
            list(sync_items(qdrant_source(config, "clusters", 1, "job", manager)))
        assert http.call_count == 1
        assert error_message_matches(str(error.value), QdrantSource().get_non_retryable_errors()) == (
            status in (401, 403)
        )


@pytest.mark.parametrize("status", [429, 500])
def test_transient_probe_errors_remain_retryable(config: QdrantSourceConfig, status: int) -> None:
    with (
        requests_mock.Mocker() as http,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
        ),
    ):
        http.get(ACCOUNTS_URL, status_code=status, json={"code": status}, headers={"Retry-After": "0"})
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(config)
        assert http.call_count > 1


def test_other_probe_error_propagates(config: QdrantSourceConfig) -> None:
    with requests_mock.Mocker() as http:
        http.get(ACCOUNTS_URL, status_code=400, json={"code": 400})
        with pytest.raises(HTTPError):
            validate_credentials(config)


def test_invalid_sync_settings_fail_before_request(config: QdrantSourceConfig, manager: Mock) -> None:
    with requests_mock.Mocker() as http:
        with pytest.raises(ValueError, match="Unknown Qdrant table"):
            qdrant_source(config, "unknown", 1, "job", manager)
        config.account_id = "../account"
        with pytest.raises(ValueError, match="valid Qdrant account ID"):
            qdrant_source(config, "clusters", 1, "job", manager)
        assert not http.called
