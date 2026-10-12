import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevenshifts import (
    SevenShiftsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.sevenshifts import (
    sevenshifts_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.source import SevenShiftsSource


@pytest.fixture
def config() -> SevenShiftsSourceConfig:
    return SevenShiftsSourceConfig(access_token="test-access-token", company_id="123")


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.fixture
def send() -> Iterator[MagicMock]:
    with (
        Session() as session,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ),
        patch.object(session, "send") as send,
    ):
        yield send


def response(rows: list[dict[str, object]], cursor: str | None = None, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://api.7shifts.com/v2/company/123/locations"
    result._content = json.dumps({"data": rows, "meta": {"cursor": {"next": cursor}}}).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.mark.parametrize(
    ("endpoint", "watermark", "expected"),
    [
        ("locations", "2026-03-05T12:30:00Z", "2026-03-04"),
        ("departments", "2026-03-05T12:30:00Z", "2026-03-04"),
        ("roles", "2026-03-05T12:30:00Z", "2026-03-04"),
        ("users", "2026-03-05T00:00:00+02:00", "2026-03-03"),
        ("shifts", "2026-03-05T12:30:00Z", "2026-03-05T12:29:59+00:00"),
        ("time_punches", datetime(2026, 3, 5, 12, 30, tzinfo=UTC), "2026-03-05T12:29:59+00:00"),
        ("time_punches", datetime(2026, 3, 5, 12, 30), "2026-03-05T12:29:59+00:00"),
    ],
)
@pytest.mark.parametrize("incremental", [True, False])
def test_incremental_filter_and_full_refresh(
    config: SevenShiftsSourceConfig,
    manager: MagicMock,
    send: MagicMock,
    endpoint: str,
    watermark: str | datetime,
    expected: str,
    incremental: bool,
) -> None:
    send.side_effect = [response([{"id": 1}], "page-two"), response([])]
    result = sevenshifts_source(config, endpoint, "2026-01-01", 1, "test-job", manager, incremental, watermark)
    list(cast(Iterable[Any], result.items()))
    for call in send.call_args_list:
        params = parse_qs(urlparse(call.args[0].url).query)
        assert params.get("modified_since") == ([expected] if incremental else None)


def test_repeated_cursor_fails(config: SevenShiftsSourceConfig, manager: MagicMock, send: MagicMock) -> None:
    send.side_effect = [response([{"id": 1}], "same-cursor"), response([{"id": 1}], "same-cursor")]
    result = sevenshifts_source(config, "users", "2026-01-01", 1, "test-job", manager, False, None)
    with pytest.raises(ValueError, match="not advancing"):
        list(cast(Iterable[Any], result.items()))


def test_missing_data_fails(config: SevenShiftsSourceConfig, manager: MagicMock, send: MagicMock) -> None:
    payload = response([])
    payload._content = b'{"unexpected": []}'
    send.return_value = payload
    result = sevenshifts_source(config, "users", "2026-01-01", 1, "test-job", manager, False, None)
    with pytest.raises(ValueError, match="data_selector"):
        list(cast(Iterable[Any], result.items()))


@pytest.mark.parametrize("company_id", ["", "abc", "0", "-1", "123/../users", "１２３"])
def test_invalid_company_id_stops_before_request(
    config: SevenShiftsSourceConfig, send: MagicMock, company_id: str
) -> None:
    config.company_id = company_id
    assert validate_credentials(config, "2026-01-01") == (False, "Enter a positive numeric 7shifts company ID.")
    send.assert_not_called()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, (True, None)),
        (
            401,
            (False, "7shifts rejected the access token. Create a token in Settings > Developer Tools, then reconnect."),
        ),
        (403, (False, "7shifts denied access. Check the company ID, token administrator, and your plan's API access.")),
        (404, (False, "7shifts could not find this company. Check the company ID.")),
    ],
)
def test_credential_probe(
    config: SevenShiftsSourceConfig, send: MagicMock, status: int, expected: tuple[bool, str | None]
) -> None:
    send.return_value = response([], "unused-next-page", status=status)
    assert validate_credentials(config, "2026-01-01") == expected
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.url == "https://api.7shifts.com/v2/company/123/locations?limit=1"
    assert request.headers["Authorization"] == "Bearer test-access-token"
    assert request.headers["x-api-version"] == "2026-01-01"


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_error_classification(
    config: SevenShiftsSourceConfig, manager: MagicMock, send: MagicMock, status: int
) -> None:
    send.return_value = response([], status=status)
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client._stop_after_client_attempts",
        return_value=True,
    ):
        result = sevenshifts_source(config, "users", "2026-01-01", 1, "test-job", manager, False, None)
        error_type = RESTClientRetryableError if status in (429, 500) else HTTPError
        with pytest.raises(error_type) as caught:
            list(cast(Iterable[Any], result.items()))
    patterns = SevenShiftsSource().get_non_retryable_errors()
    assert any(pattern in str(caught.value) for pattern in patterns) == (status in (401, 403))


def test_unexpected_probe_error_propagates(config: SevenShiftsSourceConfig, send: MagicMock) -> None:
    send.return_value = response([], status=400)
    with pytest.raises(HTTPError):
        validate_credentials(config, "2026-01-01")


def test_unknown_table(config: SevenShiftsSourceConfig, manager: MagicMock, send: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        sevenshifts_source(config, "unknown", "2026-01-01", 1, "test-job", manager, False, None)
    send.assert_not_called()
