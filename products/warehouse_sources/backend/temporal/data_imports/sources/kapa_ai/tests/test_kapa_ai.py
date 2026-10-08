import json
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.kapa_ai import (
    kapa_ai_source,
    validate_credentials,
)

PROJECT_ID = "00000000-0000-4000-8000-000000000001"
API_KEY = "test-kapa-key"
BASE_URL = "https://api.kapa.ai"


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = BASE_URL
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.fixture
def http() -> Iterator[MagicMock]:
    with patch("requests.sessions.Session.send") as send:
        yield send


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def source(endpoint: str, manager: MagicMock) -> SourceResponse:
    return kapa_ai_source(API_KEY, PROJECT_ID, endpoint, 1, "test-job", manager)


def pages(result: SourceResponse) -> list[list[dict[str, Any]]]:
    return list(cast(Iterable[list[dict[str, Any]]], result.items()))


@pytest.mark.parametrize(
    "endpoint,body,expected",
    [
        ("integrations", [{"id": "integration-1"}], [{"id": "integration-1"}]),
        ("integrations", [], []),
        (
            "activity",
            {"aggregate_statistics": {"total_query_count": 4}, "statistics_by_integration": []},
            [
                {
                    "aggregate_statistics": {"total_query_count": 4},
                    "statistics_by_integration": [],
                    "project_id": PROJECT_ID,
                }
            ],
        ),
    ],
)
def test_unpaginated_responses_keep_their_shape(
    http: MagicMock, manager: MagicMock, endpoint: str, body: object, expected: list[dict[str, Any]]
) -> None:
    http.return_value = response(body)
    result = source(endpoint, manager)
    assert pages(result) == ([expected] if expected else [])
    assert http.call_count == 1
    assert not urlsplit(http.call_args.args[0].url).query
    assert all(key in row for row in expected for key in result.primary_keys or [])


@pytest.mark.parametrize("endpoint,api_path", [("top_questions", "top-questions"), ("coverage_gaps", "coverage-gaps")])
def test_period_fanout_paginates_both_levels_and_resumes_children(
    http: MagicMock, manager: MagicMock, endpoint: str, api_path: str
) -> None:
    period1 = {"id": "period-1", "start_date": "2025-01-01", "end_date": "2025-02-01", "interval": "monthly"}
    period2 = {**period1, "id": "period-2", "start_date": "2025-02-01"}
    parent_page1 = response({"periods": [period1], "next_cursor": "period-page-2"})
    parent_page2 = response({"periods": [period2], "next_cursor": None})
    http.side_effect = [
        parent_page1,
        response(
            {"clusters": [{"id": "cluster-1", "thread_count": 123, "threads": []}], "next_cursor": "cluster-page-2"}
        ),
        response({"clusters": [{"id": "cluster-2"}], "next_cursor": None}),
        parent_page2,
        response({"clusters": [{"id": "cluster-1"}], "next_cursor": None}),
    ]
    result = source(endpoint, manager)
    rows = [row for page in pages(result) for row in page]
    assert [(row["period_id"], row["id"]) for row in rows] == [
        ("period-1", "cluster-1"),
        ("period-1", "cluster-2"),
        ("period-2", "cluster-1"),
    ]
    assert rows[0]["period_start_date"] == "2025-01-01"
    assert rows[0]["thread_count"] == 123
    assert rows[0]["threads"] == []
    assert result.primary_keys == ["period_id", "id"]
    assert result.partition_keys == ["period_start_date"]
    urls = [call.args[0].url for call in http.call_args_list]
    assert urlsplit(urls[1]).path == f"/query/v1/{api_path}/periods/period-1/"
    assert parse_qs(urlsplit(urls[2]).query)["cursor"] == ["cluster-page-2"]
    assert parse_qs(urlsplit(urls[3]).query)["cursor"] == ["period-page-2"]
    manager.can_resume.return_value = True
    manager.load_state.return_value = manager.save_state.call_args_list[0].args[0]
    http.reset_mock(side_effect=True)
    http.side_effect = [
        parent_page1,
        response({"clusters": [{"id": "cluster-2"}], "next_cursor": None}),
        parent_page2,
        response({"clusters": [], "next_cursor": None}),
    ]
    assert [row["id"] for page in pages(source(endpoint, manager)) for row in page] == ["cluster-2"]
    assert parse_qs(urlsplit(http.call_args_list[1].args[0].url).query)["cursor"] == ["cluster-page-2"]


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "Your kapa.ai API key is invalid or expired. Create a new key and reconnect."),
        (
            403,
            None,
            False,
            "Your kapa.ai API key cannot access this data. Check the key's project access and permissions.",
        ),
        (
            403,
            "sources",
            False,
            "Your kapa.ai API key cannot access this data. Check the key's project access and permissions.",
        ),
        (404, None, False, "The kapa.ai project was not found. Check your project ID and the key's project access."),
    ],
)
def test_credential_probe_status_mapping(
    http: MagicMock, status: int, schema: str | None, valid: bool, message: str | None
) -> None:
    http.return_value = response({"results": [], "next_cursor": None}, status)
    assert validate_credentials(API_KEY, PROJECT_ID, 1, schema) == (valid, message)
    assert http.call_count == 1
    assert parse_qs(urlsplit(http.call_args.args[0].url).query)["page_size"] == ["1"]


@pytest.mark.parametrize(
    "project_id,key,schema,message",
    [
        ("../threads", API_KEY, None, "Enter a valid kapa.ai project ID in UUID format."),
        (PROJECT_ID, "bad\nkey", None, "Enter a valid kapa.ai API key without whitespace or unsupported characters."),
        (PROJECT_ID, "", None, "Enter a valid kapa.ai API key without whitespace or unsupported characters."),
        (PROJECT_ID, API_KEY, "missing", "Unknown kapa.ai table. Refresh the table list and try again."),
    ],
)
def test_invalid_configuration_never_sends_a_request(
    http: MagicMock, project_id: str, key: str, schema: str | None, message: str
) -> None:
    assert validate_credentials(key, project_id, 1, schema) == (False, message)
    http.assert_not_called()


def test_unexpected_probe_error_is_not_reported_as_bad_credentials(http: MagicMock) -> None:
    http.return_value = response({}, 400)
    with pytest.raises(HTTPError):
        validate_credentials(API_KEY, PROJECT_ID, 1)


def test_missing_response_collection_fails_instead_of_erasing_the_table(http: MagicMock, manager: MagicMock) -> None:
    http.return_value = response({"unexpected": []})
    with pytest.raises(ValueError, match="results"):
        pages(source("threads", manager))
    manager.clear_state.assert_not_called()


@pytest.mark.parametrize("next_url", ["https://example.com/collect", "http://api.kapa.ai/query/v1/threads/"])
def test_pagination_cannot_send_the_key_to_another_origin(http: MagicMock, manager: MagicMock, next_url: str) -> None:
    http.return_value = response({"results": [{"id": "user-1"}], "next": next_url})
    with pytest.raises(ValueError, match="Refusing to send request"):
        pages(source("end_users", manager))
    assert http.call_count == 1
