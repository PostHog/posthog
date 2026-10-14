import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import patch

from requests import RequestException, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.semrush import (
    semrush_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    PROJECT_ERROR,
    PROJECT_ID_ERROR,
    QUOTA_ERROR,
    REQUEST_ERROR,
    UNAVAILABLE_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.source import SemrushSource


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.mark.parametrize(
    "status,body,message",
    [
        (401, "Unauthorized", AUTH_ERROR),
        (403, "Forbidden", ACCESS_ERROR),
        (400, {"code": 70, "message": "API key hash failure"}, AUTH_ERROR),
        (400, {"code": 120, "message": "Wrong key-ID pair"}, AUTH_ERROR),
        (400, {"code": 121, "message": "Wrong format or empty hash"}, AUTH_ERROR),
        (400, {"code": 122, "message": "Wrong format or empty key"}, AUTH_ERROR),
        (400, {"code": 130, "message": "API disabled"}, ACCESS_ERROR),
        (400, {"code": 131, "message": "Limit exceeded"}, QUOTA_ERROR),
        (400, {"code": 132, "message": "API units balance is zero"}, QUOTA_ERROR),
        (400, {"code": 134, "message": "Total limit exceeded"}, QUOTA_ERROR),
        (400, {"code": 512, "message": "Can't find project with project_id 123"}, PROJECT_ERROR),
        (200, {"code": "132", "message": "API units balance is zero"}, QUOTA_ERROR),
        (400, {"code": 519, "message": "Missing mandatory URL parameter"}, REQUEST_ERROR),
        (404, {"message": "Not found"}, REQUEST_ERROR),
    ],
)
def test_errors_stop_sync_and_explain_validation_failure(status: int, body: object, message: str) -> None:
    with patch.object(Session, "send", return_value=response(body, status)) as send:
        with pytest.raises(ValueError, match=message):
            list(cast(Iterable[Any], semrush_source("fake-api-key", "123", "site_audit", 1, "job").items()))
        assert send.call_count == 1
        assert validate_credentials("fake-api-key", "123", 1) == (False, message)
        assert send.call_count == 2
    assert message in SemrushSource().get_non_retryable_errors()


@pytest.mark.parametrize(
    "status,body", [(429, {}), (500, {}), (503, {}), (200, {"code": 511, "message": "Unknown error"})]
)
def test_transient_errors_retry(status: int, body: object) -> None:
    failed = response(body, status)
    failed.headers["Retry-After"] = "0"
    with (
        patch.object(Session, "send", side_effect=[failed, response({"id": 123})]) as send,
        patch("tenacity.nap.time.sleep"),
    ):
        assert validate_credentials("fake-api-key", "123", 1) == (True, None)
    assert send.call_count == 2


def test_connection_failure_reports_unavailable() -> None:
    with patch.object(Session, "send", side_effect=RequestException("boom")):
        assert validate_credentials("fake-api-key", "123", 1) == (False, UNAVAILABLE_ERROR)


@pytest.mark.parametrize("project_id", ["", "../456", "123?key=other", "https://example.com", "１２３", "123/456"])
def test_invalid_project_id_never_makes_a_request(project_id: str) -> None:
    with patch.object(Session, "send") as send:
        assert validate_credentials("fake-api-key", project_id, 1) == (False, PROJECT_ID_ERROR)
        with pytest.raises(ValueError, match=PROJECT_ID_ERROR):
            semrush_source("fake-api-key", project_id, "site_audit", 1, "job")
    send.assert_not_called()


def test_unknown_table_never_makes_a_request() -> None:
    with patch.object(Session, "send") as send:
        with pytest.raises(UnknownResourceError):
            semrush_source("fake-api-key", "123", "unknown", 1, "job")
    send.assert_not_called()


@pytest.mark.parametrize(
    "endpoint,body,message",
    [
        ("site_audit_snapshots", {"message": "Unexpected response"}, "Required data_selector"),
        ("site_audit", {"code": 999, "message": "Unexpected error"}, "record without its ID"),
        ("site_audit_snapshots", {"snapshots": [{"finish_date": 1700000000000}]}, "record without its ID"),
    ],
)
def test_malformed_records_fail_instead_of_erasing_rows(endpoint: str, body: object, message: str) -> None:
    with patch.object(Session, "send", return_value=response(body)):
        with pytest.raises(ValueError, match=message):
            list(cast(Iterable[Any], semrush_source("fake-api-key", "123", endpoint, 1, "job").items()))
