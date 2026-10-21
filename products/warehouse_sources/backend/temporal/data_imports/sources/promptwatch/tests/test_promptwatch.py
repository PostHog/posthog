import re
from datetime import UTC, datetime
from typing import Any

import pytest
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
    "endpoint,body",
    [
        ("prompts", {"prompts": [{"id": "prompt"}], "totalPages": 1}),
        ("monitors", [{"id": "monitor"}]),
        ("tags", {"tags": [{"id": "tag"}]}),
        ("topics", {"topics": [{"id": "topic"}]}),
        ("personas", {"personas": [{"id": "persona"}]}),
    ],
)
def test_configuration_tables(endpoint: str, body: object) -> None:
    config = PromptWatchSourceConfig(api_key="fake-api-key", start_date="2026-01-01")

    result = run(config, endpoint, [ScriptedResponse(json=body)])

    assert len(result.items) == 1 and len(result.items[0]) == 1
    assert len(result.requests) == 1
    assert result.requests[0].path == f"/api/v2/{endpoint}"
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
