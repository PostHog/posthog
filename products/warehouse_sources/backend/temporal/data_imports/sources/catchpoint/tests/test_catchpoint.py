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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
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


def driver() -> SourceDriver:
    return SourceDriver(CatchpointSource(), CatchpointSourceConfig(api_key="test-api-key"))


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


def test_resume_starts_at_saved_url() -> None:
    saved_url = f"{BASE_URL}/tests?pageNumber=7&pageSize=100"
    result = driver().run(
        "tests",
        [ScriptedResponse(json={"completed": True, "data": {"tests": [{"id": 701}], "hasMore": False}})],
        resume_state=CatchpointResumeConfig(next_url=saved_url),
    )

    assert result.raised is None
    assert result.rows == [{"id": 701}]
    assert result.urls == [saved_url]
    assert result.saved_states == []


@pytest.mark.parametrize("resume", [False, True])
def test_off_host_pagination_cannot_receive_key(resume: bool) -> None:
    next_url = "https://example.com/collect"
    result = driver().run(
        "tests",
        [ScriptedResponse(json={"completed": True, "data": {"tests": [{"id": 1}], "hasMore": True, "next": next_url}})],
        resume_state=CatchpointResumeConfig(next_url=next_url) if resume else None,
    )

    assert isinstance(result.raised, ValueError)
    assert "disallowed host" in str(result.raised)
    assert len(result.requests) == (0 if resume else 1)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"completed": False, "errors": [{"message": "Private vendor detail"}]}, INCOMPLETE_ERROR),
        ({"completed": True, "data": {"unexpected": []}}, "Required data_selector"),
    ],
)
def test_unexpected_response_does_not_replace_table_with_empty_data(body: dict[str, Any], error: str) -> None:
    result = driver().run("tests", [ScriptedResponse(json=body)])

    assert isinstance(result.raised, ValueError)
    assert error in str(result.raised)
    assert "Private vendor detail" not in str(result.raised)
    assert len(result.requests) == 1
    assert result.saved_states == []


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_authentication_error_mapping(status: int, message: str) -> None:
    result = driver().run("tests", [ScriptedResponse(status=status)])

    assert isinstance(result.raised, HTTPError)
    matches = [
        value
        for pattern, value in CatchpointSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert matches == [message]
    assert len(result.requests) == 1


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
