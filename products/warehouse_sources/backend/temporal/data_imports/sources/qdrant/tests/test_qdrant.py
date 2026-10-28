from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qdrant import QdrantSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.qdrant import (
    QdrantResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qdrant.source import QdrantSource

ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
ACCOUNTS_URL = "https://api.cloud.qdrant.io/api/account/v1/accounts"
CLUSTERS_URL = f"https://api.cloud.qdrant.io/api/cluster/v1/accounts/{ACCOUNT_ID}/clusters"


@pytest.fixture
def config() -> QdrantSourceConfig:
    return QdrantSourceConfig(api_key="fake-management-key", account_id=ACCOUNT_ID)


def drive(config: QdrantSourceConfig, schema_name: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(QdrantSource(), config).run(schema_name, script, **inputs)


@pytest.mark.parametrize("resume", [None, QdrantResumeConfig(cursor="saved-token")])
@pytest.mark.parametrize("body", [{"items": []}, {}, {"items": [], "nextPageToken": ""}])
def test_resume_and_empty_terminal_page(
    config: QdrantSourceConfig, resume: QdrantResumeConfig | None, body: dict[str, Any]
) -> None:
    result = drive(config, "clusters", [ScriptedResponse(json=body)], resume_state=resume)

    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 1
    assert result.paths == [urlsplit(CLUSTERS_URL).path]
    assert result.params("pageSize") == ["100"]
    assert result.params("pageToken") == (["saved-token"] if resume else [None])
    assert result.saved_states == []


def test_empty_page_with_cursor_continues(config: QdrantSourceConfig) -> None:
    result = drive(
        config,
        "clusters",
        [
            ScriptedResponse(json={"items": [], "nextPageToken": "next"}),
            ScriptedResponse(json={"items": [{"id": "last"}]}),
        ],
    )

    assert result.items == [[{"id": "last"}]]
    assert len(result.requests) == 2
    assert result.saved_states == [QdrantResumeConfig(cursor="next")]


def test_repeated_cursor_fails(config: QdrantSourceConfig) -> None:
    result = drive(
        config,
        "clusters",
        [ScriptedResponse(json={"items": [{"id": "first"}], "nextPageToken": "repeated"})],
        resume_state=QdrantResumeConfig(cursor="repeated"),
    )

    assert isinstance(result.raised, ValueError)
    assert "pagination is not advancing" in str(result.raised)
    assert len(result.requests) == 1


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
def test_sync_http_errors_are_not_retried(config: QdrantSourceConfig, status: int) -> None:
    result = drive(
        config,
        "clusters",
        [ScriptedResponse(status=status, json={"code": status, "message": "authentication failed"})],
    )

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    assert error_message_matches(str(result.raised), QdrantSource().get_non_retryable_errors()) == (
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


def test_invalid_sync_settings_fail_before_request(config: QdrantSourceConfig) -> None:
    unknown_table = drive(config, "unknown", [])
    assert isinstance(unknown_table.raised, ValueError)
    assert "Unknown Qdrant table" in str(unknown_table.raised)
    assert unknown_table.requests == []

    config.account_id = "../account"
    bad_account = drive(config, "clusters", [])
    assert isinstance(bad_account.raised, ValueError)
    assert "valid Qdrant account ID" in str(bad_account.raised)
    assert bad_account.requests == []
