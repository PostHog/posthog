from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.serpstat import (
    SerpstatSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.serpstat import SerpstatResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.settings import (
    AUTH_ERROR,
    MAX_PAGES,
    PAGE_SIZE,
    QUOTA_ERROR,
    REQUEST_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.source import SerpstatSource

CONFIG = SerpstatSourceConfig(api_key="example-token+/", project_id="123", project_region_id="456")


def request_json(request: RecordedRequest) -> dict[str, Any]:
    return request.json()


def reply(status: int, body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def drive(endpoint: str, script: list[ScriptedResponse], resume: SerpstatResumeConfig | None = None) -> Any:
    return SourceDriver(SerpstatSource(), CONFIG).run(endpoint, script, resume_state=resume)


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
    endpoint: str,
    method: str,
    params: dict[str, Any],
    result: dict[str, Any],
    row: dict[str, Any],
) -> None:
    run = drive(
        endpoint,
        [reply(200, {"id": "posthog", "result": result})],
        SerpstatResumeConfig(page=1, date_to="2026-10-05"),
    )
    assert run.raised is None
    assert run.items == [[row]]
    assert len(run.requests) == 1
    request = run.requests[0]
    assert request.method == "POST"
    assert urlsplit(request.url).path == "/v4/"
    assert parse_qs(urlsplit(request.url).query) == {"token": [CONFIG.api_key]}
    assert "authorization" not in request.headers
    assert request.headers["content-type"] == "application/json"
    assert request_json(request) == {"id": "posthog", "method": method, "params": params}
    assert run.saved_states == []


@pytest.mark.parametrize("endpoint,total_key", [("projects", "page_total"), ("project_keywords", "pages_count")])
@pytest.mark.parametrize("start_page,terminal", [(1, "total"), (2, "empty"), (MAX_PAGES, "cap")])
def test_pagination_resume_and_caps(endpoint: str, total_key: str, start_page: int, terminal: str) -> None:
    total = start_page + 1 if terminal == "total" else 100
    row = {"id": 1, "project_id": "123"}
    script = [reply(200, {"result": {"data": [row] * PAGE_SIZE, "summary_info": {total_key: total}}})]
    if terminal != "cap":
        script.append(
            reply(200, {"result": {"data": [row] if terminal == "total" else [], "summary_info": {total_key: total}}})
        )
    run = drive(
        endpoint,
        script,
        SerpstatResumeConfig(page=start_page, date_to="2026-01-02") if start_page != 1 else None,
    )
    assert [request_json(request)["params"]["page"] for request in run.requests] == (
        [start_page] if terminal == "cap" else [start_page, start_page + 1]
    )
    assert len(run.saved_states) == (0 if terminal == "cap" else 1)
    if terminal != "cap":
        assert run.saved_states[-1].page == start_page + 1


def test_positions_resume_keeps_original_date_window() -> None:
    run = drive(
        "project_positions",
        [
            reply(200, {"result": {"data": [{"keyword_id": 1}], "summary_info": {"pages_count": 3}}}),
            reply(200, {"result": {"data": [{"keyword_id": 2}], "summary_info": {"pages_count": 3}}}),
        ],
        SerpstatResumeConfig(page=2, date_to="2025-01-01"),
    )
    for request in run.requests:
        params = request_json(request)["params"]
        assert params["date_from"] == "2024-12-26"
        assert params["date_to"] == "2025-01-01"
    assert run.saved_states == [SerpstatResumeConfig(page=3, date_to="2025-01-01")]


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
def test_errors_fail_without_exposing_vendor_message(status: int, code: int, message: str, expected: str) -> None:
    run = drive("projects", [reply(status, {"error": {"code": code, "message": message + " " + CONFIG.api_key}})])
    assert isinstance(run.raised, ValueError)
    assert str(run.raised) == expected
    assert len(run.requests) == 1


def test_missing_result_fails_instead_of_replacing_table_with_empty_data() -> None:
    run = drive("projects", [reply(200, {"id": "posthog", "result": {"unexpected": []}})])
    assert isinstance(run.raised, ValueError)
