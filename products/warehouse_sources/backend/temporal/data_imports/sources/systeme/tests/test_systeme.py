from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.systeme import (
    SystemeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source import SystemeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.systeme import (
    SystemeResumeConfig,
    systeme_source,
    validate_credentials,
)


@pytest.fixture(autouse=True)
def transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
        lambda **kwargs: requests.Session(),
    )


def manager(resume: SystemeResumeConfig | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = resume is not None
    result.load_state.return_value = resume
    return result


def rows(response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]


@pytest.mark.parametrize(
    "endpoint,path",
    [
        ("contacts", "contacts"),
        ("tags", "tags"),
        ("newsletters", "mailing/newsletters"),
        ("courses", "school/courses"),
        ("enrollments", "school/enrollments"),
        ("communities", "community/communities"),
        ("memberships", "community/memberships"),
    ],
)
def test_pagination_auth_and_terminal_page(requests_mock: Mocker, endpoint: str, path: str) -> None:
    requests_mock.get(
        f"https://api.systeme.io/api/{path}",
        [
            {"json": {"items": [{"id": 30}, {"id": 20}], "hasMore": True}},
            {"json": {"items": [{"id": 10}], "hasMore": False}},
        ],
    )
    state = manager()
    response = systeme_source("test-key", endpoint, 1, "job", state)
    pages = iter(cast(Iterable[list[dict[str, Any]]], response.items()))
    assert next(pages) == [{"id": 30}, {"id": 20}]
    state.save_state.assert_not_called()
    assert next(pages) == [{"id": 10}]
    state.save_state.assert_called_once_with(SystemeResumeConfig(cursor=20))
    assert list(pages) == []
    assert state.save_state.call_args.args[0] == SystemeResumeConfig(completed=True)
    first, second = requests_mock.request_history
    assert first.qs == {"limit": ["100"], "order": ["desc"]}
    assert second.qs == {"limit": ["100"], "order": ["desc"], "startingafter": ["20"]}
    assert all(request.headers["X-API-Key"] == "test-key" for request in requests_mock.request_history)


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected",
    [
        ("contacts", True, datetime(2026, 1, 2, tzinfo=UTC), "2026-01-02T00:00:00+00:00"),
        ("contacts", True, "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
        ("contacts", True, None, None),
        ("contacts", False, "2026-01-02T00:00:00Z", None),
        ("tags", True, "2026-01-02T00:00:00Z", None),
    ],
)
def test_incremental_filter_and_full_refresh(
    requests_mock: Mocker, endpoint: str, incremental: bool, watermark: datetime | str | None, expected: str | None
) -> None:
    requests_mock.get(
        f"https://api.systeme.io/api/{endpoint}",
        [
            {"json": {"items": [{"id": 20}], "hasMore": True}},
            {"json": {"items": [{"id": 10}], "hasMore": False}},
        ],
    )
    response = systeme_source("key", endpoint, 1, "job", manager(), incremental, watermark)
    assert rows(response) == [{"id": 20}, {"id": 10}]
    assert response.sort_mode == "desc"
    for request in requests_mock.request_history:
        assert request.qs.get("registeredafter") == ([expected.lower()] if expected else None)


@pytest.mark.parametrize("resume_cursor", [None, 40])
def test_empty_terminal_page_and_resume(requests_mock: Mocker, resume_cursor: int | None) -> None:
    requests_mock.get("https://api.systeme.io/api/contacts", json={"items": [], "hasMore": False})
    state = manager(SystemeResumeConfig(cursor=resume_cursor) if resume_cursor else None)
    assert rows(systeme_source("key", "contacts", 1, "job", state)) == []
    assert requests_mock.call_count == 1
    last_request = requests_mock.last_request
    assert last_request is not None
    assert last_request.qs.get("startingafter") == ([str(resume_cursor)] if resume_cursor else None)
    state.save_state.assert_called_once_with(SystemeResumeConfig(completed=True))


def test_completed_resume_does_not_fetch(requests_mock: Mocker) -> None:
    assert rows(systeme_source("key", "contacts", 1, "job", manager(SystemeResumeConfig(completed=True)))) == []
    assert requests_mock.call_count == 0


@pytest.mark.parametrize(
    "body,message",
    [
        ({"items": [], "hasMore": True}, "invalid pagination data"),
        ({"items": [{"id": 20}]}, "invalid pagination data"),
        ({"items": [{"id": 0}], "hasMore": True}, "invalid record ID"),
        ({"items": [{"id": "20"}], "hasMore": True}, "invalid record ID"),
        ({"items": [{"id": True}], "hasMore": True}, "invalid record ID"),
        ({"items": [{"id": 20}], "hasMore": True}, "repeated cursor"),
    ],
)
def test_invalid_or_repeated_cursor_fails(requests_mock: Mocker, body: dict[str, Any], message: str) -> None:
    requests_mock.get("https://api.systeme.io/api/contacts", json=body)
    state = manager(SystemeResumeConfig(cursor=20))
    with pytest.raises(ValueError, match=message):
        rows(systeme_source("key", "contacts", 1, "job", state))
    assert requests_mock.call_count == 1
    state.save_state.assert_not_called()


@pytest.mark.parametrize("status,expected", [(200, None), (401, "rejected your API key"), (403, "account permissions")])
@pytest.mark.parametrize("schema,path", [(None, "contacts"), ("newsletters", "mailing/newsletters")])
def test_validate_credentials_status_and_probe(
    requests_mock: Mocker, status: int, expected: str | None, schema: str | None, path: str
) -> None:
    requests_mock.get(
        f"https://api.systeme.io/api/{path}",
        status_code=status,
        json={"items": [{"id": 10}], "hasMore": True}
        if status == 200
        else {"detail": "Full authentication is required to access this resource."},
    )
    valid, message = validate_credentials("test-key", schema)
    assert valid is (status == 200)
    if expected:
        assert expected in (message or "")
    else:
        assert message is None
    assert requests_mock.call_count == 1
    last_request = requests_mock.last_request
    assert last_request is not None
    assert last_request.qs == {"limit": ["10"]}
    assert last_request.headers["X-API-Key"] == "test-key"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_sync_error_classification(requests_mock: Mocker, status: int) -> None:
    requests_mock.get("https://api.systeme.io/api/contacts", status_code=status, json={"detail": "Request failed"})
    error_type = RESTClientRetryableError if status >= 500 or status == 429 else requests.HTTPError
    with pytest.raises(error_type) as caught:
        rows(systeme_source("test-key", "contacts", 1, "job", manager()))
    matched = [
        message
        for pattern, message in SystemeSource().get_non_retryable_errors().items()
        if pattern in str(caught.value)
    ]
    assert bool(matched) is (status in (401, 403))
    assert "test-key" not in str(caught.value)
    assert requests_mock.call_count == (5 if status in (429, 500) else 1)


@pytest.mark.parametrize("status", [404, 429, 500])
def test_probe_does_not_report_transient_or_other_errors_as_invalid_key(requests_mock: Mocker, status: int) -> None:
    requests_mock.get("https://api.systeme.io/api/contacts", status_code=status, json={"detail": "Request failed"})
    error_type = RESTClientRetryableError if status in (429, 500) else requests.HTTPError
    with pytest.raises(error_type):
        validate_credentials("key")


def test_source_adapter_forwards_pipeline_inputs() -> None:
    source = SystemeSource()
    config = SystemeSourceConfig(api_key="key")
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = "contacts"
    inputs.team_id = 1
    inputs.job_id = "job"
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "2026-01-02T00:00:00Z"

    resumable_manager = MagicMock(spec=ResumableSourceManager)
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source.validate_systeme_credentials",
            return_value=(True, None),
        ) as mock_validate,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source.ResumableSourceManager",
            return_value=resumable_manager,
        ) as mock_manager_class,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.systeme.source.systeme_source",
            return_value=MagicMock(spec=SourceResponse),
        ) as mock_source,
    ):
        assert source.validate_credentials(config, inputs.team_id, inputs.schema_name) == (True, None)
        mock_validate.assert_called_once_with("key", "contacts")

        assert source.get_resumable_source_manager(inputs) is resumable_manager
        mock_manager_class.assert_called_once_with(inputs, SystemeResumeConfig)
        source.source_for_pipeline(config, resumable_manager, inputs)
        mock_source.assert_called_once_with(
            api_key="key",
            endpoint="contacts",
            team_id=1,
            job_id="job",
            resumable_source_manager=resumable_manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-02T00:00:00Z",
        )


def test_unknown_endpoint_does_not_fetch(requests_mock: Mocker) -> None:
    with pytest.raises(UnknownResourceError):
        systeme_source("key", "unknown", 1, "job", manager())
    with pytest.raises(UnknownResourceError):
        validate_credentials("key", "unknown")
    assert requests_mock.call_count == 0
