from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast

import pytest
from unittest.mock import MagicMock, patch

import requests_mock
from requests import HTTPError

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptwatch import (
    PromptWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.promptwatch import (
    PromptWatchResumeConfig,
    promptwatch_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.settings import (
    AUTH_ERROR,
    BASE_URL,
    MAX_PAGES,
    NON_RETRYABLE_ERRORS,
    PROJECT_ERROR,
    QUOTA_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.source import PromptWatchSource


@pytest.fixture
def config() -> PromptWatchSourceConfig:
    return PromptWatchSourceConfig(api_key="fake-api-key", project_id="test-project", start_date="2026-01-01")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="responses",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=True,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field="createdAt",
        incremental_field_type=None,
        job_id="job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


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
    inputs: SourceInputs,
    manager: MagicMock,
    incremental: bool,
    watermark: str | datetime | None,
    expected: str,
) -> None:
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = watermark
    with requests_mock.Mocker() as mock:
        mock.get(
            f"{BASE_URL}/v2/responses",
            [
                {"json": {"responses": [{"id": "first"}], "totalPages": 2}},
                {"json": {"responses": [{"id": "last"}], "totalPages": 2}},
            ],
        )
        response = PromptWatchSource().source_for_pipeline(config, manager, inputs)
        items = cast(Iterable[list[dict[str, str]]], response.items())
        assert list(items) == [[{"id": "first"}], [{"id": "last"}]]
        assert response.sort_mode == "asc"
        assert len(mock.request_history) == 2
        for index, request in enumerate(mock.request_history, start=1):
            assert request.headers["X-API-Key"] == "fake-api-key"
            assert request.headers["X-Project-Id"] == "test-project"
            assert request.qs["page"] == [str(index)]
            assert request.qs["size"] == ["50"]
            assert request.qs["sortby"] == ["createdat"]
            assert request.qs["sortorder"] == ["asc"]
            assert request.qs["from"] == [expected.lower()]
            assert request.qs["until"] == mock.request_history[0].qs["until"]
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [2, 0]


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
def test_configuration_tables(
    config: PromptWatchSourceConfig, inputs: SourceInputs, manager: MagicMock, endpoint: str, body: object
) -> None:
    inputs.schema_name = endpoint
    config.project_id = None
    with requests_mock.Mocker() as mock:
        mock.get(f"{BASE_URL}/v2/{endpoint}", json=body)
        pages = list(promptwatch_source(config, inputs, manager, "v2"))
        assert len(pages) == 1 and len(pages[0]) == 1
        assert len(mock.request_history) == 1
        assert "from" not in mock.last_request.qs
        assert "until" not in mock.last_request.qs
        assert "X-Project-Id" not in mock.last_request.headers


@pytest.mark.parametrize("page", [0, 2])
def test_resume(config: PromptWatchSourceConfig, inputs: SourceInputs, manager: MagicMock, page: int) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = PromptWatchResumeConfig(
        page=page, from_date="2026-01-02T00:00:00+00:00", until="2026-01-03T00:00:00+00:00"
    )
    inputs.db_incremental_field_last_value = "2026-01-02T12:00:00Z"
    with requests_mock.Mocker() as mock:
        mock.get(f"{BASE_URL}/v2/responses", json={"responses": [{"id": "last"}], "totalPages": 2})
        pages = list(promptwatch_source(config, inputs, manager, "v2"))
        if page == 0:
            assert pages == []
            assert mock.call_count == 0
        else:
            assert pages == [[{"id": "last"}]]
            assert mock.last_request.qs["page"] == ["2"]
            assert mock.last_request.qs["from"] == ["2026-01-02t00:00:00+00:00"]
            assert mock.last_request.qs["until"] == ["2026-01-03t00:00:00+00:00"]


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
    inputs: SourceInputs,
    manager: MagicMock,
    rows: list[dict[str, str]],
    total_pages: int,
    incremental: bool,
    error: str | None,
    expected_pages: int,
) -> None:
    inputs.should_use_incremental_field = incremental
    with (
        requests_mock.Mocker() as mock,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.promptwatch.logger"
        ) as logger,
    ):
        mock.get(f"{BASE_URL}/v2/responses", json={"responses": rows, "totalPages": total_pages})
        if error:
            with pytest.raises(NonReportableError, match=error):
                list(promptwatch_source(config, inputs, manager, "v2"))
            assert error in NON_RETRYABLE_ERRORS
        else:
            assert list(promptwatch_source(config, inputs, manager, "v2")) == ([rows] * expected_pages if rows else [])
        assert [request.qs["page"] for request in mock.request_history] == [
            [str(page)] for page in range(1, expected_pages + 1)
        ]
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
        (401, {"message": "Invalid API key"}, AUTH_ERROR),
        (403, {"message": "Forbidden"}, PROJECT_ERROR),
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
    with requests_mock.Mocker() as mock:
        mock.get(f"{BASE_URL}/v2/auth/validate", status_code=status, json=body)
        assert validate_credentials(config, "v2") == (message is None, message)
        assert mock.call_count == 1
        assert mock.last_request.headers["X-API-Key"] == "fake-api-key"
        assert mock.last_request.headers["X-Project-Id"] == "test-project"


def test_invalid_date(config: PromptWatchSourceConfig) -> None:
    config.start_date = "not-a-date"
    with requests_mock.Mocker() as mock:
        assert validate_credentials(config, "v2") == (False, "Enter the response start date in YYYY-MM-DD format.")
        assert mock.call_count == 0


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
def test_error_classification(
    config: PromptWatchSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
    body: dict[str, str],
    retry: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RESTClient._send_request.retry, "wait", lambda _: 0)  # type: ignore[attr-defined]
    with requests_mock.Mocker() as mock:
        mock.get(
            f"{BASE_URL}/v2/responses",
            [
                {"status_code": status, "json": body},
                {"json": {"responses": [], "totalPages": 0}},
            ],
        )
        if retry:
            list(promptwatch_source(config, inputs, manager, "v2"))
            assert mock.call_count == 2
        else:
            with pytest.raises((HTTPError, NonReportableError)) as exc:
                list(promptwatch_source(config, inputs, manager, "v2"))
            assert any(pattern in str(exc.value) for pattern in PromptWatchSource().get_non_retryable_errors())
            assert mock.call_count == 1


@pytest.mark.parametrize("total_pages", [None, "2", -1, True])
def test_invalid_pagination(
    config: PromptWatchSourceConfig, inputs: SourceInputs, manager: MagicMock, total_pages: object
) -> None:
    with requests_mock.Mocker() as mock:
        mock.get(f"{BASE_URL}/v2/responses", json={"responses": [{"id": "record"}], "totalPages": total_pages})
        with pytest.raises(ValueError, match="invalid pagination metadata"):
            list(promptwatch_source(config, inputs, manager, "v2"))
        assert mock.call_count == 1


@pytest.mark.parametrize("status", [200, 429])
def test_malformed_response_retries(
    config: PromptWatchSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RESTClient._send_request.retry, "wait", lambda _: 0)  # type: ignore[attr-defined]
    with requests_mock.Mocker() as mock:
        mock.get(
            f"{BASE_URL}/v2/responses",
            [
                {"status_code": status, "text": '{"responses":'},
                {"json": {"responses": [], "totalPages": 0}},
            ],
        )
        list(promptwatch_source(config, inputs, manager, "v2"))
        assert mock.call_count == 2
