from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.catchpoint import (
    CatchpointResumeConfig,
    catchpoint_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.settings import (
    AUTH_ERROR,
    INCOMPLETE_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.source import CatchpointSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.catchpoint import (
    CatchpointSourceConfig,
)

BASE_URL = "https://io.catchpoint.com/api/v3"


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def source_response(manager: MagicMock, endpoint: str = "tests") -> SourceResponse:
    return catchpoint_source("test-api-key", "v3", endpoint, 1, "test-job", manager)


def rows(response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [("tests", "tests"), ("nodes", "nodes/all"), ("products", "products"), ("folders", "folders")],
)
def test_paginated_collections(manager: MagicMock, endpoint: str, path: str) -> None:
    next_path = f"/api/v3/{path}?pageNumber=2&pageSize=100"
    next_url = f"https://io.catchpoint.com{next_path}"
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/{path}?pageNumber=1&pageSize=100",
            json={"completed": True, "data": {endpoint: [{"id": 1}], "hasMore": True, "next": next_path}},
            complete_qs=True,
        )
        http.get(
            next_url,
            json={"completed": True, "data": {endpoint: [{"id": 2}], "hasMore": False, "next": None}},
            complete_qs=True,
        )
        response = source_response(manager, endpoint)
        assert rows(response) == [{"id": 1}, {"id": 2}]
        assert http.call_count == 2
        assert response.primary_keys == ["id"]
        for request in http.request_history:
            assert request.headers["Authorization"] == "Bearer test-api-key"
            assert request.headers["Accept"] == "application/json"
        assert parse_qs(urlsplit(http.request_history[1].url).query) == {"pageNumber": ["2"], "pageSize": ["100"]}
    manager.save_state.assert_called_once_with(CatchpointResumeConfig(next_url=next_url))
    manager.clear_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once()


def test_resume_starts_at_saved_url(manager: MagicMock) -> None:
    saved_url = f"{BASE_URL}/tests?pageNumber=7&pageSize=100"
    manager.can_resume.return_value = True
    manager.load_state.return_value = CatchpointResumeConfig(next_url=saved_url)
    with requests_mock.Mocker() as http:
        http.get(
            saved_url,
            json={"completed": True, "data": {"tests": [{"id": 701}], "hasMore": False}},
            complete_qs=True,
        )
        assert rows(source_response(manager)) == [{"id": 701}]
        assert http.call_count == 1
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("resume", [False, True])
def test_off_host_pagination_cannot_receive_key(manager: MagicMock, resume: bool) -> None:
    next_url = "https://example.com/collect"
    if resume:
        manager.can_resume.return_value = True
        manager.load_state.return_value = CatchpointResumeConfig(next_url=next_url)
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/tests",
            json={"completed": True, "data": {"tests": [{"id": 1}], "hasMore": True, "next": next_url}},
        )
        with pytest.raises(ValueError, match="disallowed host"):
            rows(source_response(manager))
        assert http.call_count == (0 if resume else 1)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"completed": False, "errors": [{"message": "Private vendor detail"}]}, INCOMPLETE_ERROR),
        ({"completed": True, "data": {"unexpected": []}}, "Required data_selector"),
    ],
)
def test_unexpected_response_does_not_replace_table_with_empty_data(
    manager: MagicMock, body: dict[str, Any], error: str
) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/tests", json=body)
        with pytest.raises(ValueError, match=error) as caught:
            rows(source_response(manager))
        assert "Private vendor detail" not in str(caught.value)
        assert http.call_count == 1
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_authentication_error_mapping(manager: MagicMock, status: int, message: str) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/tests", status_code=status)
        with pytest.raises(HTTPError) as caught:
            rows(source_response(manager))
        matches = [
            value
            for pattern, value in CatchpointSource().get_non_retryable_errors().items()
            if pattern in str(caught.value)
        ]
        assert matches == [message]
        assert http.call_count == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, (True, None)), (401, (False, AUTH_ERROR)), (403, (False, PERMISSION_ERROR))],
)
def test_credential_validation(status: int, expected: tuple[bool, str | None]) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/useridentity", status_code=status, json={"completed": True, "data": {"id": 1}})
        result = CatchpointSource().validate_credentials(CatchpointSourceConfig(api_key="test-api-key"), team_id=1)
        assert result == expected
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.headers["Authorization"] == "Bearer test-api-key"


def test_credential_validation_preserves_non_auth_errors() -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/useridentity", status_code=400)
        with pytest.raises(HTTPError):
            CatchpointSource().validate_credentials(CatchpointSourceConfig(api_key="test-api-key"), team_id=1)
