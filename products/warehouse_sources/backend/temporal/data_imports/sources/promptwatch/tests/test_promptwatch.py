import re
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from requests import HTTPError

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptwatch import (
    PromptWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.promptwatch import (
    PromptWatchResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.settings import (
    AUTH_ERROR,
    BASE_URL,
    MAX_PAGES,
    NON_RETRYABLE_ERRORS,
    QUOTA_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.source import PromptWatchSource

LOGGER_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.promptwatch.logger"


@pytest.fixture
def config() -> PromptWatchSourceConfig:
    return PromptWatchSourceConfig(api_key="fake-api-key", project_id="test-project", start_date="2026-01-01")


def run(config: PromptWatchSourceConfig, schema_name: str, script: Any, **kwargs: Any) -> DriveResult:
    return SourceDriver(PromptWatchSource(), config).run(schema_name, script, **kwargs)


def incremental_inputs(incremental: bool, watermark: object = None) -> dict[str, Any]:
    # The driver syncs incrementally whenever it is given a field to sync on.
    inputs: dict[str, Any] = {"db_incremental_field_last_value": watermark}
    if incremental:
        inputs["incremental_field"] = "createdAt"
    return inputs


@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (False, "2026-02-03T12:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        (True, None, "2026-01-01T00:00:00+00:00"),
        (True, "2026-02-03T12:00:00+00:00", "2026-02-03T11:59:59+00:00"),
        (True, datetime(2026, 2, 3, 12, tzinfo=UTC), "2026-02-03T11:59:59+00:00"),
        (True, datetime(2026, 2, 3, 12), "2026-02-03T11:59:59+00:00"),
    ],
)
def test_response_requests(
    config: PromptWatchSourceConfig,
    incremental: bool,
    watermark: str | datetime | None,
    expected: str,
) -> None:
    result = run(
        config,
        "responses",
        [
            ScriptedResponse(json={"responses": [{"id": "first"}], "totalPages": 2}),
            ScriptedResponse(json={"responses": [{"id": "last"}], "totalPages": 2}),
        ],
        **incremental_inputs(incremental, watermark),
    )

    assert result.items == [[{"id": "first"}], [{"id": "last"}]]
    assert result.response is not None
    assert result.response.sort_mode == "asc"
    assert len(result.requests) == 2
    for index, request in enumerate(result.requests, start=1):
        assert request.headers["x-api-key"] == "fake-api-key"
        assert request.headers["x-project-id"] == "test-project"
        assert request.param("page") == str(index)
        assert request.param("size") == "50"
        assert request.param("sortBy") == "createdAt"
        assert request.param("sortOrder") == "asc"
        assert request.param("from") == expected
        assert request.param("until") == result.requests[0].param("until")
    assert [state.page for state in result.saved_states] == [2, 0]


@pytest.mark.parametrize(
    "endpoint,body,params",
    [
        ("prompts", {"prompts": [{"id": "prompt"}], "totalPages": 1}, {"sortBy": "createdAt"}),
        ("monitors", [{"id": "monitor"}], {}),
        ("tags", {"tags": [{"id": "tag"}]}, {}),
        ("topics", {"topics": [{"id": "topic"}]}, {}),
        ("personas", {"personas": [{"id": "persona"}]}, {}),
        ("models", {"models": [{"id": "model"}], "total": 1}, {"includeDeprecated": "true"}),
        ("brands", {"brands": [{"id": "brand"}], "total": 1, "totalPages": 1}, {"page": "1", "sortBy": None}),
    ],
)
def test_configuration_tables(endpoint: str, body: object, params: dict[str, str | None]) -> None:
    config = PromptWatchSourceConfig(api_key="fake-api-key", start_date="2026-01-01")

    result = run(config, endpoint, [ScriptedResponse(json=body)])

    assert len(result.items) == 1 and len(result.items[0]) == 1
    assert len(result.requests) == 1
    assert result.requests[0].path == f"/api/v2/{endpoint}"
    for name, value in params.items():
        assert result.requests[0].param(name) == value
    assert "from" not in result.requests[0].query
    assert "until" not in result.requests[0].query
    assert "x-project-id" not in result.requests[0].headers


@pytest.mark.parametrize("page", [0, 2])
def test_resume(config: PromptWatchSourceConfig, page: int) -> None:
    result = run(
        config,
        "responses",
        [ScriptedResponse(json={"responses": [{"id": "last"}], "totalPages": 2})],
        resume_state=PromptWatchResumeConfig(
            page=page, from_date="2026-01-02T00:00:00+00:00", until="2026-01-03T00:00:00+00:00"
        ),
        **incremental_inputs(True, "2026-01-02T12:00:00Z"),
    )

    if page == 0:
        assert result.items == []
        assert result.requests == []
    else:
        assert result.items == [[{"id": "last"}]]
        assert result.requests[-1].param("page") == "2"
        assert result.requests[-1].param("from") == "2026-01-02T00:00:00+00:00"
        assert result.requests[-1].param("until") == "2026-01-03T00:00:00+00:00"


def test_a_run_with_no_saved_state_starts_from_the_first_page(config: PromptWatchSourceConfig) -> None:
    result = run(config, "responses", [ScriptedResponse(json={"responses": [], "totalPages": 0})])

    assert result.requests[0].param("page") == "1"


@pytest.mark.parametrize(
    "rows,total_pages,incremental,error,expected_pages",
    [
        ([], 0, True, None, 1),
        ([{"id": "record"}], MAX_PAGES + 1, False, "PROMPTWATCH_ROW_LIMIT", 1),
        ([{"id": "record"}], MAX_PAGES + 1, True, None, MAX_PAGES),
    ],
)
def test_empty_and_oversized_tables(
    config: PromptWatchSourceConfig,
    rows: list[dict[str, str]],
    total_pages: int,
    incremental: bool,
    error: str | None,
    expected_pages: int,
) -> None:
    with patch(LOGGER_PATCH) as logger:
        result = run(
            config,
            "responses",
            lambda _request: ScriptedResponse(json={"responses": rows, "totalPages": total_pages}),
            **incremental_inputs(incremental),
        )

    if error:
        assert isinstance(result.raised, NonReportableError)
        assert re.search(error, str(result.raised))
        assert error in NON_RETRYABLE_ERRORS
    else:
        assert result.raised is None
        assert result.items == ([rows] * expected_pages if rows else [])
    assert result.params("page") == [str(page) for page in range(1, expected_pages + 1)]
    if total_pages > MAX_PAGES and incremental:
        logger.warning.assert_called_once_with(
            "promptwatch.page_cap_reached", maximum_page=MAX_PAGES, total_pages=total_pages
        )
    else:
        logger.warning.assert_not_called()


@pytest.mark.parametrize(
    "status,body,message",
    [
        (200, {"valid": True, "project": {"id": "test-project"}}, None),
        (200, {"valid": False}, AUTH_ERROR),
        (200, {"valid": True, "project": None}, "Enter a project ID when you use an organization API key."),
        (
            429,
            {
                "message": "You've hit your hourly API request limit of 500 requests. Try again in 30 minutes, or upgrade your plan to increase your limit."
            },
            QUOTA_ERROR,
        ),
    ],
)
def test_credential_validation(
    config: PromptWatchSourceConfig, status: int, body: dict[str, object], message: str | None
) -> None:
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        assert validate_credentials(config, "v2") == (message is None, message)

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == f"{BASE_URL}/v2/auth/validate"
    assert request.headers["x-api-key"] == "fake-api-key"
    assert request.headers["x-project-id"] == "test-project"


def test_invalid_date(config: PromptWatchSourceConfig) -> None:
    config.start_date = "not-a-date"
    with scripted_network([]) as network:
        assert validate_credentials(config, "v2") == (False, "Enter the response start date in YYYY-MM-DD format.")
    assert network.requests_log == []


@pytest.mark.parametrize(
    "status,body,retry",
    [
        (401, {"message": "Invalid API key"}, False),
        (403, {"message": "Forbidden"}, False),
        (429, {"message": "You've hit your hourly API request limit of 500 requests."}, False),
        (429, {"message": "You're sending requests too quickly."}, True),
        (500, {"error": "Internal Server Error"}, True),
    ],
)
def test_error_classification(config: PromptWatchSourceConfig, status: int, body: dict[str, str], retry: bool) -> None:
    result = run(
        config,
        "responses",
        [
            ScriptedResponse(status=status, json=body),
            ScriptedResponse(json={"responses": [], "totalPages": 0}),
        ],
        **incremental_inputs(True),
    )

    if retry:
        assert result.raised is None
        assert len(result.requests) == 2
    else:
        assert isinstance(result.raised, HTTPError | NonReportableError)
        assert any(pattern in str(result.raised) for pattern in PromptWatchSource().get_non_retryable_errors())
        assert len(result.requests) == 1


@pytest.mark.parametrize("total_pages", [None, "2", -1, True])
def test_invalid_pagination(config: PromptWatchSourceConfig, total_pages: object) -> None:
    result = run(
        config,
        "responses",
        [ScriptedResponse(json={"responses": [{"id": "record"}], "totalPages": total_pages})],
        **incremental_inputs(True),
    )

    assert isinstance(result.raised, ValueError)
    assert "invalid pagination metadata" in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [200, 429])
def test_malformed_response_retries(config: PromptWatchSourceConfig, status: int) -> None:
    result = run(
        config,
        "responses",
        [
            ScriptedResponse(status=status, body=b'{"responses":'),
            ScriptedResponse(json={"responses": [], "totalPages": 0}),
        ],
        **incremental_inputs(True),
    )

    assert result.raised is None
    assert len(result.requests) == 2


def citation(url_id: str) -> dict[str, Any]:
    return {"url": {"id": url_id, "url": f"https://{url_id}.example.com", "domain": {"domainName": "example.com"}}}


@time_machine.travel(datetime(2026, 5, 10, 15, tzinfo=UTC), tick=False)
def test_grouped_citations(config: PromptWatchSourceConfig) -> None:
    result = run(
        config,
        "grouped_citations",
        [
            ScriptedResponse(json={"data": [citation("a")], "pagination": {"totalPages": 2}}),
            ScriptedResponse(json={"data": [citation("b")], "pagination": {"totalPages": 2}}),
        ],
    )

    assert result.raised is None
    assert [row["urlId"] for row in result.rows] == ["a", "b"]
    assert result.rows[0]["url"]["url"] == "https://a.example.com"
    assert result.response is not None
    assert result.response.primary_keys == ["urlId"]
    assert result.response.sort_mode is None
    assert result.paths == ["/api/v2/citations/grouped"] * 2
    assert result.params("page") == ["1", "2"]
    assert result.params("startDate") == ["2026-02-08"] * 2
    assert result.params("endDate") == ["2026-05-10"] * 2
    assert result.params("sortBy") == ["count"] * 2
    assert result.params("sortOrder") == ["desc"] * 2
    assert "from" not in result.requests[0].query
    assert [state.page for state in result.saved_states] == [2, 0]


def test_grouped_citations_resume_keeps_the_saved_window(config: PromptWatchSourceConfig) -> None:
    result = run(
        config,
        "grouped_citations",
        [ScriptedResponse(json={"data": [citation("b")], "pagination": {"totalPages": 2}})],
        resume_state=PromptWatchResumeConfig(page=2, from_date="2026-01-01", until="2026-04-01"),
    )

    assert [row["urlId"] for row in result.rows] == ["b"]
    assert result.params("page") == ["2"]
    assert result.params("startDate") == ["2026-01-01"]
    assert result.params("endDate") == ["2026-04-01"]


@pytest.mark.parametrize(
    "endpoint,body,error",
    [
        ("grouped_citations", {"data": [citation("a")], "pagination": {"totalPages": MAX_PAGES + 1}}, None),
        ("brands", {"brands": [{"id": "brand"}], "total": 2000, "totalPages": MAX_PAGES + 1}, "PROMPTWATCH_ROW_LIMIT"),
        ("grouped_citations", {"data": [citation("a")], "pagination": {}}, "invalid pagination metadata"),
        ("grouped_citations", {"data": [citation("a")], "pagination": None}, "invalid pagination metadata"),
    ],
)
def test_page_limits_for_new_tables(
    config: PromptWatchSourceConfig, endpoint: str, body: dict[str, Any], error: str | None
) -> None:
    with patch(LOGGER_PATCH) as logger:
        result = run(config, endpoint, lambda _request: ScriptedResponse(json=body))

    if error:
        assert result.raised is not None
        assert error in str(result.raised)
        assert len(result.requests) == 1
    else:
        assert result.raised is None
        assert result.params("page") == [str(page) for page in range(1, MAX_PAGES + 1)]
        logger.warning.assert_called_once_with(
            "promptwatch.page_cap_reached", maximum_page=MAX_PAGES, total_pages=MAX_PAGES + 1
        )


def visitor_body(dates: list[str], series: dict[str, list[int]]) -> dict[str, Any]:
    return {"dates": dates, "series": [{"name": name, "data": data} for name, data in series.items()]}


@time_machine.travel(datetime(2026, 5, 10, 15, tzinfo=UTC), tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,windows",
    [
        (False, None, [("2026-03-12", "2026-05-10")]),
        (True, None, [("2026-03-12", "2026-05-10")]),
        (False, "2026-05-08", [("2026-03-12", "2026-05-10")]),
        (True, "2026-05-08", [("2026-05-07", "2026-05-10")]),
        (True, datetime(2026, 5, 8, 0, tzinfo=UTC), [("2026-05-07", "2026-05-10")]),
        (True, "2026-05-12", []),
        (
            True,
            "2026-01-01",
            [("2025-12-31", "2026-02-28"), ("2026-03-01", "2026-04-29"), ("2026-04-30", "2026-05-10")],
        ),
    ],
)
def test_visitor_trend_windows(
    config: PromptWatchSourceConfig,
    incremental: bool,
    watermark: str | datetime | None,
    windows: list[tuple[str, str]],
) -> None:
    result = run(
        config,
        "visitor_trends",
        lambda _request: ScriptedResponse(json=visitor_body([], {})),
        **incremental_inputs(incremental, watermark),
    )

    assert result.raised is None
    assert result.rows == []
    assert result.paths == ["/api/v2/analytics/visitors/trend"] * len(windows)
    assert list(zip(result.params("startDate"), result.params("endDate"))) == windows
    assert result.params("timezone") == ["UTC"] * len(windows)


@time_machine.travel(datetime(2026, 3, 15, 15, tzinfo=UTC), tick=False)
def test_visitor_trend_rows(config: PromptWatchSourceConfig) -> None:
    result = run(
        config,
        "visitor_trends",
        [
            ScriptedResponse(
                json=visitor_body(["2026-03-14", "2026-03-15"], {"chatgpt.com": [620, 655], "claude.ai": [0, 12]})
            )
        ],
        **incremental_inputs(True, "2026-03-15"),
    )

    assert result.raised is None
    assert result.rows == [
        {"date": "2026-03-14", "referrer": "chatgpt.com", "visitors": 620},
        {"date": "2026-03-15", "referrer": "chatgpt.com", "visitors": 655},
        {"date": "2026-03-14", "referrer": "claude.ai", "visitors": 0},
        {"date": "2026-03-15", "referrer": "claude.ai", "visitors": 12},
    ]
    assert result.response is not None
    assert result.response.primary_keys == ["date", "referrer"]
    assert result.saved_states == []


@time_machine.travel(datetime(2026, 3, 15, 15, tzinfo=UTC), tick=False)
def test_visitor_trend_series_length_mismatch_fails(config: PromptWatchSourceConfig) -> None:
    result = run(
        config,
        "visitor_trends",
        [ScriptedResponse(json=visitor_body(["2026-03-14", "2026-03-15"], {"chatgpt.com": [620]}))],
        **incremental_inputs(True, "2026-03-15"),
    )

    assert isinstance(result.raised, ValueError)
