import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.serpstat import (
    SerpstatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.serpstat import (
    SerpstatResumeConfig,
    serpstat_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.settings import (
    AUTH_ERROR,
    MAX_PAGES,
    PAGE_SIZE,
    QUOTA_ERROR,
    REQUEST_ERROR,
)

CONFIG = SerpstatSourceConfig(api_key="example-token+/", project_id="123", project_region_id="456")


def request_json(request: PreparedRequest) -> dict[str, Any]:
    assert request.body is not None
    return json.loads(request.body)


@pytest.fixture
def transport() -> Iterator[tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]]]:
    sent: list[PreparedRequest] = []
    responses: list[tuple[int, dict[str, Any]]] = []

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        sent.append(request)
        status, body = responses.pop(0)
        response = Response()
        response.status_code = status
        assert request.url is not None
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body).encode()
        return response

    with Session() as session:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
                return_value=session,
            ),
            patch.object(session, "send", side_effect=send),
        ):
            yield sent, responses


@pytest.mark.parametrize(
    ("endpoint", "method", "params", "result", "row"),
    [
        (
            "projects",
            "ProjectProcedure.getProjects",
            {"size": 100, "page": 1},
            {"data": [{"project_id": "123"}], "summary_info": {"page_total": 1}},
            {"project_id": "123"},
        ),
        (
            "project_keywords",
            "RtApiProcedure.getProjectKeywords",
            {"project_id": 123, "size": 100, "page": 1, "sort": "added", "order": "asc"},
            {"data": [{"id": 7, "keyword_id": 8}], "summary_info": {"pages_count": 1}},
            {"id": 7, "keyword_id": 8, "project_id": 123},
        ),
        (
            "project_regions",
            "RtApiSearchEngineProcedure.getProjectRegions",
            {"projectId": 123},
            {"projectId": 123, "regions": [{"id": 456, "active": True}]},
            {"id": 456, "active": True, "project_id": 123},
        ),
        (
            "project_tags",
            "RtApiProcedure.getProjectTags",
            {"project_id": 123},
            {"data": [{"tag_uuid": "example-tag", "tag": "blog"}]},
            {"tag_uuid": "example-tag", "tag": "blog", "project_id": 123},
        ),
        (
            "project_positions",
            "RtApiProcedure.getProjectPositions",
            {
                "project_id": 123,
                "project_region_ids": [456],
                "page_size": 100,
                "page": 1,
                "sort": "added",
                "order": "asc",
                "date_from": "2026-09-29",
                "date_to": "2026-10-05",
            },
            {
                "data": [{"keyword_id": 8, "regions": [{"project_region_id": 456, "positions": []}]}],
                "summary_info": {"pages_count": 1},
            },
            {"keyword_id": 8, "project_id": 123, "regions": [{"project_region_id": 456, "positions": []}]},
        ),
    ],
)
def test_request_and_rows(
    transport: tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]],
    endpoint: str,
    method: str,
    params: dict[str, Any],
    result: dict[str, Any],
    row: dict[str, Any],
) -> None:
    sent, responses = transport
    responses.append((200, {"id": "posthog", "result": result}))
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = True
    manager.load_state.return_value = SerpstatResumeConfig(page=1, date_to="2026-10-05")
    resource = serpstat_resource(CONFIG, endpoint, 1, "test-job", "v4", manager)
    assert list(resource) == [[row]]
    assert len(sent) == 1
    request = sent[0]
    assert request.method == "POST"
    assert request.url is not None
    assert urlsplit(request.url).path == "/v4/"
    assert parse_qs(urlsplit(request.url).query) == {"token": [CONFIG.api_key]}
    assert "Authorization" not in request.headers
    assert request.headers["Content-Type"] == "application/json"
    assert request_json(request) == {"id": "posthog", "method": method, "params": params}
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("endpoint,total_key", [("projects", "page_total"), ("project_keywords", "pages_count")])
@pytest.mark.parametrize("start_page,terminal", [(1, "total"), (2, "empty"), (MAX_PAGES, "cap")])
def test_pagination_resume_and_caps(
    transport: tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]],
    endpoint: str,
    total_key: str,
    start_page: int,
    terminal: str,
) -> None:
    sent, responses = transport
    total = start_page + 1 if terminal == "total" else 100
    row = {"id": 1, "project_id": "123"}
    responses.append((200, {"result": {"data": [row] * PAGE_SIZE, "summary_info": {total_key: total}}}))
    if terminal != "cap":
        responses.append(
            (200, {"result": {"data": [row] if terminal == "total" else [], "summary_info": {total_key: total}}})
        )
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = start_page != 1
    manager.load_state.return_value = SerpstatResumeConfig(page=start_page, date_to="2026-01-02")
    list(serpstat_resource(CONFIG, endpoint, 1, "test-job", "v4", manager))
    assert [request_json(request)["params"]["page"] for request in sent] == (
        [start_page] if terminal == "cap" else [start_page, start_page + 1]
    )
    assert manager.save_state.call_count == (0 if terminal == "cap" else 1)
    if terminal != "cap":
        assert manager.save_state.call_args.args[0].page == start_page + 1
    if start_page == 1:
        manager.load_state.assert_not_called()


def test_positions_resume_keeps_original_date_window(
    transport: tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]],
) -> None:
    sent, responses = transport
    responses.extend(
        [
            (200, {"result": {"data": [{"keyword_id": 1}], "summary_info": {"pages_count": 3}}}),
            (200, {"result": {"data": [{"keyword_id": 2}], "summary_info": {"pages_count": 3}}}),
        ]
    )
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = True
    manager.load_state.return_value = SerpstatResumeConfig(page=2, date_to="2025-01-01")
    list(serpstat_resource(CONFIG, "project_positions", 1, "test-job", "v4", manager))
    for request in sent:
        params = request_json(request)["params"]
        assert params["date_from"] == "2024-12-26"
        assert params["date_to"] == "2025-01-01"
    manager.save_state.assert_called_once_with(SerpstatResumeConfig(page=3, date_to="2025-01-01"))


@pytest.mark.parametrize(
    "status,code,message,expected",
    [
        (200, -32020, "Invalid token!", AUTH_ERROR),
        (200, -32602, "Invalid token", AUTH_ERROR),
        (401, 401, "Unauthorized", AUTH_ERROR),
        (403, 403, "Problems with authorization", AUTH_ERROR),
        (200, -32012, "Credits exceeded", QUOTA_ERROR),
        (200, 32012, "Credits exceeded", QUOTA_ERROR),
        (200, 403, "Not enough credits", QUOTA_ERROR),
        (200, 402, "Pricing plan credits exceeded", QUOTA_ERROR),
        (402, 402, "Payment required", QUOTA_ERROR),
        (200, -32602, "Invalid project ID", REQUEST_ERROR),
        (400, 400, "Invalid request", REQUEST_ERROR),
    ],
)
def test_errors_fail_without_exposing_vendor_message(
    transport: tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]],
    status: int,
    code: int,
    message: str,
    expected: str,
) -> None:
    sent, responses = transport
    responses.append((status, {"error": {"code": code, "message": message + " " + CONFIG.api_key}}))
    with pytest.raises(ValueError) as error:
        list(serpstat_resource(CONFIG, "projects", 1, "test-job", "v4"))
    assert str(error.value) == expected
    assert len(sent) == 1


def test_missing_result_fails_instead_of_replacing_table_with_empty_data(
    transport: tuple[list[PreparedRequest], list[tuple[int, dict[str, Any]]]],
) -> None:
    _, responses = transport
    responses.append((200, {"id": "posthog", "result": {"unexpected": []}}))
    with pytest.raises(ValueError):
        list(serpstat_resource(CONFIG, "projects", 1, "test-job", "v4"))
