import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.peecai import PeecAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.peec_ai import (
    PeecAIResumeConfig,
    peec_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.source import PeecAISource

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.peec_ai"


def items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


def request_params(request: PreparedRequest) -> dict[str, list[str]]:
    assert request.url is not None
    return parse_qs(urlsplit(request.url).query)


class HTTPStub:
    def __init__(self) -> None:
        self.requests: list[PreparedRequest] = []
        self.responses: list[tuple[int, dict[str, Any]]] = []

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        response = Response()
        response.status_code = status
        response.reason = HTTPStatus(status).phrase
        response.url = request.url or ""
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body).encode()
        return response


@pytest.fixture
def http() -> Iterator[HTTPStub]:
    stub = HTTPStub()
    session = requests.Session()
    with (
        patch.object(session, "send", side_effect=stub.send),
        patch(f"{TRANSPORT}.make_tracked_session", return_value=session),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ),
        patch(f"{TRANSPORT}.PAGE_SIZE", 2),
    ):
        yield stub


@pytest.fixture
def config() -> PeecAISourceConfig:
    return PeecAISourceConfig(api_key="example-secret", project_id="or_example", start_date="2025-01-01")


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize(
    "endpoint,path,extra",
    [
        ("chats", "chats", {"include_archived_prompts": ["true"], "sort": ["asc"]}),
        ("prompts", "prompts", {"is_archived": ["false"]}),
        ("archived_prompts", "prompts", {"is_archived": ["true"]}),
        ("brands", "brands", {}),
        ("topics", "topics", {}),
        ("tags", "tags", {}),
        ("model_channels", "model-channels", {}),
    ],
)
def test_request_auth_pagination_and_resume_checkpoints(
    http: HTTPStub,
    config: PeecAISourceConfig,
    manager: MagicMock,
    endpoint: str,
    path: str,
    extra: dict[str, list[str]],
) -> None:
    total = {} if endpoint == "model_channels" else {"total_count": 3}
    http.responses = [(200, {"data": [{"id": "a"}, {"id": "b"}], **total}), (200, {"data": [{"id": "c"}], **total})]
    response = peec_ai_source(config, endpoint, "v1", 1, "job", manager, False, None)
    batches = iter(items(response))
    assert next(batches) == [{"id": "a"}, {"id": "b"}]
    assert list(batches) == [[{"id": "c"}]]
    manager.clear_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once()
    checkpoint = manager.save_state.call_args.args[0]
    assert checkpoint.offset == 2
    manager.save_state.assert_called_once()
    for offset, request in zip([0, 2], http.requests):
        assert request.url is not None
        assert urlsplit(request.url).path == f"/customer/v1/{path}"
        params = request_params(request)
        assert params["offset"] == [str(offset)]
        assert params["limit"] == ["2"]
        assert params["project_id"] == ["or_example"]
        assert all(params[key] == value for key, value in extra.items())
        assert request.headers["x-api-key"] == "example-secret"
        assert "example-secret" not in request.url
        if endpoint != "chats":
            assert "start_date" not in params


@pytest.mark.parametrize("total,rows", [(0, []), (2, [{"id": "a"}, {"id": "b"}])])
def test_terminal_page_does_not_request_another_page(
    http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock, total: int, rows: list[dict[str, str]]
) -> None:
    http.responses = [(200, {"data": rows, "total_count": total})]
    list(items(peec_ai_source(config, "brands", "v1", 1, "job", manager, False, None)))
    assert len(http.requests) == 1
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (False, "2025-06-10", "2025-01-01"),
        (True, None, "2025-01-01"),
        (True, "2025-06-10", "2025-06-10"),
        (True, date(2025, 6, 10), "2025-06-10"),
        (True, datetime(2025, 6, 10, 12, tzinfo=UTC), "2025-06-10"),
        (True, "2024-06-10", "2025-01-01"),
    ],
)
def test_chat_date_filter(
    http: HTTPStub,
    config: PeecAISourceConfig,
    manager: MagicMock,
    incremental: bool,
    watermark: str | date | datetime | None,
    expected: str,
) -> None:
    http.responses = [(200, {"data": [], "total_count": 0})]
    response = peec_ai_source(config, "chats", "v1", 1, "job", manager, incremental, watermark)
    list(items(response))
    params = request_params(http.requests[0])
    assert params["start_date"] == [expected]
    assert params["end_date"] == [datetime.now(UTC).date().isoformat()]
    assert params["sort"] == ["asc"]
    assert response.sort_mode == "asc"


def test_resume_preserves_date_range_after_watermark_advances(
    http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = PeecAIResumeConfig(offset=4, start_date="2025-06-01", end_date="2025-06-30")
    http.responses = [(200, {"data": [{"id": "last"}], "total_count": 5})]
    list(items(peec_ai_source(config, "chats", "v1", 1, "job", manager, True, "2025-06-15")))
    params = request_params(http.requests[0])
    assert params["offset"] == ["4"]
    assert params["start_date"] == ["2025-06-01"]
    assert params["end_date"] == ["2025-06-30"]


def test_model_channels_stops_at_empty_page_without_total(
    http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock
) -> None:
    config.project_id = None
    http.responses = [(200, {"data": [{"id": "a"}, {"id": "b"}]}), (200, {"data": []})]
    batches = list(items(peec_ai_source(config, "model_channels", "v1", 1, "job", manager, False, None)))
    assert [row for batch in batches for row in batch] == [{"id": "a"}, {"id": "b"}]
    assert len(http.requests) == 2
    assert all("project_id" not in request_params(request) for request in http.requests)


def test_actions_paginate_through_post_body(http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock) -> None:
    http.responses = [
        (200, {"data": [{"id": "a"}, {"id": "b"}], "total_count": 3}),
        (200, {"data": [{"id": "c"}], "total_count": 3}),
    ]
    batches = list(items(peec_ai_source(config, "actions", "v1", 1, "job", manager, False, None)))
    assert [row for batch in batches for row in batch] == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    for offset, request in zip([0, 2], http.requests, strict=True):
        assert request.method == "POST"
        assert request.url == "https://api.peec.ai/customer/v1/actions/list"
        assert request.body is not None
        assert json.loads(request.body) == {
            "project_id": "or_example",
            "order_by": "created_at",
            "direction": "asc",
            "limit": 2,
            "offset": offset,
        }


def test_tag_groups_fetch_one_unpaginated_page(http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock) -> None:
    rows = [{"group": "persona", "color": "blue", "tag_count": 3}, {"group": "region", "color": None, "tag_count": 1}]
    http.responses = [(200, {"data": rows})]
    response = peec_ai_source(config, "tag_groups", "v1", 1, "job", manager, False, None)
    assert list(items(response)) == [rows]
    assert response.primary_keys == ["group"]
    assert len(http.requests) == 1
    assert request_params(http.requests[0]) == {"project_id": ["or_example"]}
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status", [429, 500])
def test_sync_retries_transient_errors(
    http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock, status: int
) -> None:
    http.responses = [(status, {"message": "Try later"}), (200, {"data": [{"id": "a"}], "total_count": 1})]
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
    ):
        assert list(items(peec_ai_source(config, "brands", "v1", 1, "job", manager, False, None))) == [[{"id": "a"}]]
    assert len(http.requests) == 2
    assert http.requests[0].url == http.requests[1].url


@pytest.mark.parametrize("project_id", [None, "or_example"])
def test_credential_probe_uses_one_small_request(
    http: HTTPStub, config: PeecAISourceConfig, project_id: str | None
) -> None:
    config.project_id = project_id
    http.responses = [(200, {"data": [], "total_count": 0})]
    assert validate_credentials(config, "v1") == (True, None)
    assert len(http.requests) == 1
    request = http.requests[0]
    params = request_params(request)
    assert params == {"limit": ["1"], **({"project_id": [project_id]} if project_id else {})}
    assert request.headers["x-api-key"] == "example-secret"


@pytest.mark.parametrize(
    "status,body,message",
    [
        (400, "Missing API Key", "Check your API key"),
        (401, "Invalid API Key", "Create a new key"),
        (403, "Forbidden", "plan includes API access"),
    ],
)
def test_credential_and_sync_errors(
    http: HTTPStub, config: PeecAISourceConfig, manager: MagicMock, status: int, body: str, message: str
) -> None:
    http.responses = [(status, {"message": body}), (status, {"message": body})]
    valid, reason = validate_credentials(config, "v1")
    assert not valid
    assert reason is not None and message in reason
    with pytest.raises(requests.HTTPError) as error:
        list(items(peec_ai_source(config, "brands", "v1", 1, "job", manager, False, None)))
    errors = PeecAISource().get_non_retryable_errors()
    assert any(pattern in str(error.value) and mapped == reason for pattern, mapped in errors.items())
    assert len(http.requests) == 2


@pytest.mark.parametrize("status", [429, 500])
def test_transient_probe_errors_are_not_invalid_credentials(
    http: HTTPStub, config: PeecAISourceConfig, status: int
) -> None:
    http.responses = [(status, {"message": "Try later"})]
    with pytest.raises(requests.HTTPError):
        validate_credentials(config, "v1")


@pytest.mark.parametrize("start_date", ["", "not-a-date", "2025-02-30", "20250610"])
def test_invalid_start_date_does_not_call_api(http: HTTPStub, config: PeecAISourceConfig, start_date: str) -> None:
    config.start_date = start_date
    assert validate_credentials(config, "v1") == (False, "Enter a valid start date in YYYY-MM-DD format.")
    assert not http.requests


def test_future_start_date_does_not_call_api(http: HTTPStub, config: PeecAISourceConfig) -> None:
    config.start_date = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    assert validate_credentials(config, "v1") == (False, "The start date must be today or earlier.")
    assert not http.requests
