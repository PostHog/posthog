import json
from collections.abc import Iterable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qonto import QontoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.qonto import (
    QontoResumeConfig,
    qonto_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.settings import AUTH_ERROR, PERMISSION_ERROR
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


def page(name: str, rows: list[dict[str, Any]], current: int = 1, total: int = 1) -> Response:
    return response(
        {
            name: rows,
            "meta": {
                "current_page": current,
                "total_pages": total,
                "next_page": current + 1 if current < total else None,
            },
        }
    )


def manager(state: dict[str, Any] | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = QontoResumeConfig(paginator_state=state) if state is not None else None
    return result


def source(
    endpoint: str, resume_manager: MagicMock, incremental: bool = False, last_value: str | datetime | None = None
) -> SourceResponse:
    return qonto_source(CONFIG, endpoint, "v2", 1, "test-job", resume_manager, incremental, last_value)


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
    responses = [page(endpoint, [{"id": "row"}], 1, 2), page(endpoint, [{"id": "last"}], 2, 2)]
    if endpoint == "transactions":
        responses.insert(0, response({"organization": {"bank_accounts": [{"id": "account-1"}]}}))
    with patch("requests.Session.send", side_effect=responses) as send:
        result = source(endpoint, manager(), incremental, last_value)
        list(cast(Iterable[Any], result.items()))
    requests = [call.args[0] for call in send.call_args_list if urlsplit(call.args[0].url).path != "/v2/organization"]
    for request in requests:
        params = parse_qs(urlsplit(request.url).query)
        assert params.get("updated_at_from") == ([expected] if expected else None)
        assert params["sort_by"] == ["updated_at:desc"]
        if endpoint == "transactions":
            assert params["status[]"] == ["pending", "declined", "completed", "reversed"]
            assert params["bank_account_id"] == ["account-1"]
    assert result.sort_mode == "desc"


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
    with patch(
        "requests.Session.send",
        return_value=response({"errors": [{"code": "unauthorized", "detail": "Invalid credentials"}]}, status),
    ) as send:
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], source("labels", manager()).items()))
    assert send.call_count == 1
    matches = [value for key, value in QontoSource().get_non_retryable_errors().items() if key in str(error.value)]
    assert matches == [message]


@pytest.mark.parametrize("status", [429, 500])
def test_sync_transient_errors_remain_retryable(status: int) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.DEFAULT_RETRY_ATTEMPTS", 1
    ):
        with patch("requests.Session.send", return_value=response({}, status)):
            with pytest.raises(RESTClientRetryableError) as error:
                list(cast(Iterable[Any], source("labels", manager()).items()))
    assert not any(key in str(error.value) for key in QontoSource().get_non_retryable_errors())


@pytest.mark.parametrize(
    ("endpoint", "last_value", "message"),
    [("missing", None, "Unknown Qonto table"), ("transfers", "invalid", "Invalid Qonto incremental timestamp")],
)
def test_invalid_inputs_fail_before_requests(endpoint: str, last_value: str | None, message: str) -> None:
    with patch("requests.Session.send") as send, pytest.raises(ValueError, match=message):
        source(endpoint, manager(), True, last_value)
    send.assert_not_called()
