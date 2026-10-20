import json
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

import pytest
from unittest.mock import patch

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qonto import QontoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.qonto import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.source import QontoSource

CONFIG = QontoSourceConfig(login="example-company", secret_key="fake-secret")


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://thirdparty.qonto.com/v2/organization"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


def page(name: str, rows: list[dict[str, Any]], current: int = 1, total: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            name: rows,
            "meta": {
                "current_page": current,
                "total_pages": total,
                "next_page": current + 1 if current < total else None,
            },
        }
    )


def drive(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(QontoSource(), CONFIG).run(endpoint, script, **inputs)


@pytest.mark.parametrize(
    ("incremental", "last_value", "expected"),
    [
        (False, "2025-01-02T03:04:05Z", None),
        (True, None, None),
        (True, "2025-01-02T03:04:05Z", "2025-01-02T03:04:05+00:00"),
        (True, datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC), "2025-01-02T03:04:05+00:00"),
        (True, datetime(2025, 1, 2, 3, 4, 5), "2025-01-02T03:04:05+00:00"),
    ],
)
@pytest.mark.parametrize("endpoint", ["transactions", "transfers"])
def test_incremental_filters(
    endpoint: str, incremental: bool, last_value: str | datetime | None, expected: str | None
) -> None:
    responses: list[ScriptedResponse | BaseException] = [
        page(endpoint, [{"id": "row"}], 1, 2),
        page(endpoint, [{"id": "last"}], 2, 2),
    ]
    if endpoint == "transactions":
        responses.insert(0, ScriptedResponse(json={"organization": {"bank_accounts": [{"id": "account-1"}]}}))
    result = (
        drive(endpoint, responses, incremental_field="updated_at", db_incremental_field_last_value=last_value)
        if (incremental)
        else drive(endpoint, responses, db_incremental_field_last_value=last_value)
    )

    assert result.raised is None
    requests = [request for request in result.requests if request.path != "/v2/organization"]
    assert len(requests) == 2
    for request in requests:
        assert request.param("updated_at_from") == expected
        assert request.query["sort_by"] == ("updated_at:desc",)
        if endpoint == "transactions":
            assert request.query["status[]"] == ("pending", "declined", "completed", "reversed")
            assert request.query["bank_account_id"] == ("account-1",)
    assert result.response is not None
    assert result.response.sort_mode == "desc"


@pytest.mark.parametrize(
    ("endpoint", "selector", "expected_query"),
    [
        ("labels", "labels", {"per_page": ("100",)}),
        ("beneficiaries", "beneficiaries", {"per_page": ("100",)}),
        (
            "client_invoices",
            "client_invoices",
            {"per_page": ("100",), "sort_by": ("created_at:asc",), "exclude_imported": ("false",)},
        ),
    ],
)
def test_full_refresh_endpoints_walk_every_page(
    endpoint: str, selector: str, expected_query: dict[str, tuple[str, ...]]
) -> None:
    result = drive(
        endpoint,
        [page(selector, [{"id": "first"}], 1, 2), page(selector, [{"id": "second"}], 2, 2)],
        incremental_field="updated_at",
        db_incremental_field_last_value="2025-01-02T03:04:05Z",
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["first", "second"]
    assert [request.path for request in result.requests] == [f"/v2/{ENDPOINTS[endpoint][0]}"] * 2
    assert result.params("page") == ["1", "2"]
    for request in result.requests:
        assert {key: value for key, value in request.query.items() if key != "page"} == expected_query


@pytest.mark.parametrize(
    ("status", "schema_name", "expected"),
    [
        (200, None, (True, None)),
        (401, None, (False, AUTH_ERROR)),
        (403, None, (True, None)),
        (403, "transactions", (False, PERMISSION_ERROR)),
    ],
)
def test_credential_validation(status: int, schema_name: str | None, expected: tuple[bool, str | None]) -> None:
    with patch("requests.Session.send", return_value=response({}, status)) as send:
        assert validate_credentials(CONFIG, "v2", schema_name) == expected
    send.assert_called_once()
    assert send.call_args.args[0].url == "https://thirdparty.qonto.com/v2/organization"
    assert send.call_args.args[0].headers["Authorization"] == "example-company:fake-secret"


@pytest.mark.parametrize(
    "config",
    [
        QontoSourceConfig(login="bad\nlogin", secret_key="stored-secret"),
        QontoSourceConfig(login="example-company", secret_key="bad\rsecret"),
    ],
)
def test_credential_validation_rejects_header_injection(config: QontoSourceConfig) -> None:
    with patch("requests.Session.send") as send:
        assert validate_credentials(config, "v2", None) == (False, AUTH_ERROR)
    send.assert_not_called()


@pytest.mark.parametrize("status", [429, 500])
def test_credential_validation_propagates_transient_errors(status: int) -> None:
    with patch("requests.Session.send", return_value=response({}, status)), pytest.raises(HTTPError):
        validate_credentials(CONFIG, "v2", None)


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_auth_errors_are_terminal(status: int, message: str) -> None:
    result = drive(
        "labels",
        [ScriptedResponse(status=status, json={"errors": [{"code": "unauthorized", "detail": "Invalid credentials"}]})],
    )

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    matches = [value for key, value in QontoSource().get_non_retryable_errors().items() if key in str(result.raised)]
    assert matches == [message]


@pytest.mark.parametrize("status", [429, 500])
def test_sync_transient_errors_remain_retryable(status: int) -> None:
    result = drive("labels", always(ScriptedResponse(status=status, json={})))

    assert isinstance(result.raised, RESTClientRetryableError)
    assert not any(key in str(result.raised) for key in QontoSource().get_non_retryable_errors())


@pytest.mark.parametrize(
    ("endpoint", "last_value", "message"),
    [("missing", None, "Unknown Qonto table"), ("transfers", "invalid", "Invalid Qonto incremental timestamp")],
)
def test_invalid_inputs_fail_before_requests(endpoint: str, last_value: str | None, message: str) -> None:
    result = drive(endpoint, [], incremental_field="updated_at", db_incremental_field_last_value=last_value)

    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert result.requests == []
