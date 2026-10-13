import json
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.ahrefs import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.ahrefs.source import AhrefsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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
def test_page_sample_cap(count: int) -> None:
    rows = [{"url": f"https://example.com/{i}"} for i in range(count)]
    with patch(f"{SOURCE_MODULE}.logger") as logger:
        result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
            "site_audit_pages", [ScriptedResponse(json={"pages": rows})]
        )
    assert result.raised is None
    assert result.rows == [{**row, "project_id": "123"} for row in rows[:100]]
    assert logger.info.call_count == int(count >= 100)
    assert len(result.requests) == 1


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
def test_credential_and_sync_error_mapping(status: int, body: object, message: str) -> None:
    answer = ScriptedResponse(status=status, json=body)
    with scripted_network([answer]) as network:
        valid, error = validate_credentials("test-key")
    assert valid is False
    assert error is not None and message in error
    assert len(network.requests_log) == 1

    source = AhrefsSource()
    result = SourceDriver(source, AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
        "site_audit_issues", [answer]
    )
    assert isinstance(result.raised, ValueError)
    mapped = source.get_non_retryable_errors()[str(result.raised)]
    assert mapped is not None and message in mapped
    assert len(result.requests) == 1


def test_free_credential_probe(send: MagicMock) -> None:
    send.return_value = response({"limits_and_usage": {"subscription": "Lite", "units_usage_api_key": 0}})
    assert validate_credentials("test-key") == (True, None)
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.url == "https://api.ahrefs.com/v3/subscription-info/limits-and-usage?output=json"
    assert send.call_args.kwargs["timeout"] == (10, 60)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_failure_is_not_invalid_credentials(status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"error": "Try later"}))) as network:
        with pytest.raises(RESTClientRetryableError):
            validate_credentials("test-key")
    assert network.requests_log
    assert all(request.path == "/v3/subscription-info/limits-and-usage" for request in network.requests_log)


def test_unrecognized_probe_error_propagates() -> None:
    with scripted_network([ScriptedResponse(status=400, json={"error": "Invalid request"})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials("test-key")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("probe", [False, True])
def test_missing_response_envelope_fails(probe: bool) -> None:
    answer = ScriptedResponse(json={"unexpected": []})
    if probe:
        with scripted_network([answer]) as network:
            with pytest.raises(ValueError, match="matched nothing"):
                validate_credentials("test-key")
        assert len(network.requests_log) == 1
    else:
        result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run(
            "site_audit_issues", [answer]
        )
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)
        assert len(result.requests) == 1


def test_unknown_table_fails_before_request() -> None:
    result = SourceDriver(AhrefsSource(), AhrefsSourceConfig(api_key="test-key", project_id="123")).run("unknown", [])
    assert isinstance(result.raised, UnknownResourceError)
    assert result.requests == []
