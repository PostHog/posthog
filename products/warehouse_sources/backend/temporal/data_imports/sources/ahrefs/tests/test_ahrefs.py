import json
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.ahrefs import (
    ahrefs_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.source import AhrefsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahrefs import AhrefsSourceConfig

CLIENT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.ahrefs"


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = "OK" if status == 200 else "Error"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    result.url = "https://api.ahrefs.com/v3/site-audit/issues"
    return result


@pytest.fixture
def send() -> Iterator[MagicMock]:
    with Session() as session:
        with (
            patch(f"{CLIENT_MODULE}.make_tracked_session", return_value=session),
            patch.object(session, "send") as mock,
        ):
            yield mock


@pytest.mark.parametrize(
    ("table", "path", "selector", "row", "expected_params"),
    [
        (
            "site_audit_health_scores",
            "projects",
            "healthscores",
            {"project_id": "123", "health_score": 95, "date": None},
            {},
        ),
        (
            "site_audit_issues",
            "issues",
            "issues",
            {"issue_id": "missing_title", "crawled": 3},
            {},
        ),
        (
            "site_audit_pages",
            "page-explorer",
            "pages",
            {"url": "https://example.com/", "http_code": 200, "title": ["Example"]},
            {"limit": ["100"], "select": ["url,http_code,title,depth,is_html"], "order_by": ["url:asc"]},
        ),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
def test_snapshot_request_and_terminal_page(
    send: MagicMock,
    table: str,
    path: str,
    selector: str,
    row: dict[str, object],
    expected_params: dict[str, list[str]],
    empty: bool,
) -> None:
    send.return_value = response({selector: [] if empty else [row], "next": "https://example.com/ignored"})
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = table
    inputs.team_id = 1
    inputs.job_id = "test-job"
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = "2026-01-01"
    result = AhrefsSource().source_for_pipeline(AhrefsSourceConfig(api_key="test-key", project_id="00123"), inputs)

    assert list(cast(Iterable[Any], result.items())) == ([] if empty else [[{**row, "project_id": "123"}]])
    send.assert_called_once()
    assert send.call_args.kwargs["timeout"] == (10, 60)
    request = send.call_args.args[0]
    assert request.method == "GET"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert urlparse(request.url).path == f"/v3/site-audit/{path}"
    assert parse_qs(urlparse(request.url).query) == {
        "output": ["json"],
        "project_id": ["123"],
        **expected_params,
    }


@pytest.mark.parametrize("count", [99, 100, 101])
def test_page_sample_cap(send: MagicMock, count: int) -> None:
    rows = [{"url": f"https://example.com/{i}"} for i in range(count)]
    send.return_value = response({"pages": rows})
    with patch(f"{SOURCE_MODULE}.logger") as logger:
        result = ahrefs_source("test-key", "123", "site_audit_pages", 1, "test-job")
        actual = [row for page in cast(Iterable[Any], result.items()) for row in page]
    assert actual == [{**row, "project_id": "123"} for row in rows[:100]]
    assert logger.info.call_count == int(count >= 100)
    send.assert_called_once()


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (401, {"error": "Invalid API key"}, "Check your API key"),
        (403, ["Error", "Forbidden"], "Check your plan"),
        (403, {"error": "Insufficient API units"}, "API units are exhausted"),
        (400, {"error": "API units limit exceeded"}, "API units are exhausted"),
        (403, {"error": "Quota exceeded"}, "API units are exhausted"),
        (402, {"error": "Payment required"}, "API units are exhausted"),
    ],
)
def test_credential_and_sync_error_mapping(send: MagicMock, status: int, body: object, message: str) -> None:
    send.return_value = response(body, status)
    valid, error = validate_credentials("test-key")
    assert valid is False
    assert error is not None and message in error
    send.assert_called_once()
    send.reset_mock()

    with pytest.raises(ValueError) as raised:
        list(cast(Iterable[Any], ahrefs_source("test-key", "123", "site_audit_issues", 1, "test-job").items()))
    mapped = AhrefsSource().get_non_retryable_errors()[str(raised.value)]
    assert mapped is not None and message in mapped
    send.assert_called_once()


def test_free_credential_probe(send: MagicMock) -> None:
    send.return_value = response({"limits_and_usage": {"subscription": "Lite", "units_usage_api_key": 0}})
    assert validate_credentials("test-key") == (True, None)
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.url == "https://api.ahrefs.com/v3/subscription-info/limits-and-usage?output=json"
    assert send.call_args.kwargs["timeout"] == (10, 60)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_failure_is_not_invalid_credentials(send: MagicMock, status: int) -> None:
    send.return_value = response({"error": "Try later"}, status)
    with pytest.raises(RESTClientRetryableError):
        validate_credentials("test-key")
    send.assert_called_once()


def test_unrecognized_probe_error_propagates(send: MagicMock) -> None:
    send.return_value = response({"error": "Invalid request"}, 400)
    with pytest.raises(HTTPError):
        validate_credentials("test-key")


@pytest.mark.parametrize("probe", [False, True])
def test_missing_response_envelope_fails(send: MagicMock, probe: bool) -> None:
    send.return_value = response({"unexpected": []})
    with pytest.raises(ValueError, match="matched nothing"):
        if probe:
            validate_credentials("test-key")
        else:
            list(cast(Iterable[Any], ahrefs_source("test-key", "123", "site_audit_issues", 1, "test-job").items()))


def test_unknown_table_fails_before_request(send: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        ahrefs_source("test-key", "123", "unknown", 1, "test-job")
    send.assert_not_called()
