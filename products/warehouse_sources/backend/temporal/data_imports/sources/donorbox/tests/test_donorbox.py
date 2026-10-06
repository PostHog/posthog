import json
from base64 import b64decode
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.donorbox import (
    DonorboxResumeConfig,
    donorbox_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.source import DonorboxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.donorbox import (
    DonorboxSourceConfig,
)


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found"}.get(status, "Error")
    result.url = "https://donorbox.org/api/v1/campaigns"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.fixture
def http_send() -> Iterator[MagicMock]:
    with Session() as session:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
                return_value=session,
            ),
            patch.object(session, "send") as send,
            patch.object(cast(Any, RESTClient._send_request).retry, "sleep"),
        ):
            yield send


@pytest.fixture
def credentials() -> DonorboxSourceConfig:
    return DonorboxSourceConfig(email="warehouse@example.com", api_key="test-api-key")


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def source(
    credentials: DonorboxSourceConfig,
    manager: MagicMock,
    endpoint: str = "donations",
    incremental: bool = False,
    watermark: datetime | date | str | None = None,
) -> SourceResponse:
    return donorbox_source(credentials, endpoint, 1, "test-job", manager, incremental, watermark)


def rows(result: SourceResponse) -> list[dict[str, Any]]:
    return [row for batch in cast(Iterable[list[dict[str, Any]]], result.items()) for row in batch]


@pytest.mark.parametrize("endpoint", ["campaigns", "donations", "plans", "donors", "events", "tickets", "purchases"])
def test_pagination_and_auth(
    http_send: MagicMock, credentials: DonorboxSourceConfig, manager: MagicMock, endpoint: str
) -> None:
    http_send.side_effect = [response([{"id": 1}]), response([{"id": 2}]), response([])]
    result = source(credentials, manager, endpoint)

    assert rows(result) == [{"id": 1}, {"id": 2}]
    for page, call in enumerate(http_send.call_args_list, start=1):
        request = call.args[0]
        url = urlsplit(request.url)
        assert url.scheme == "https"
        assert url.netloc == "donorbox.org"
        assert url.path == f"/api/v1/{endpoint}"
        assert parse_qs(url.query) == {"page": [str(page)], "per_page": ["100"], "order": ["desc"]}
        assert b64decode(request.headers["Authorization"].split()[1]).decode() == "warehouse@example.com:test-api-key"
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        DonorboxResumeConfig(page=2),
        DonorboxResumeConfig(page=3),
    ]
    manager.clear_state.assert_not_called()
    assert result.on_complete is not None
    result.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected",
    [
        ("donations", True, datetime(2025, 3, 2, 13, 30, tzinfo=UTC), "2025-03-01"),
        ("donations", True, "2025-03-02T13:30:00Z", "2025-03-01"),
        ("plans", True, date(2025, 3, 2), "2025-03-01"),
        ("plans", True, "2025-03-02", "2025-03-01"),
        ("donations", True, None, None),
        ("plans", True, None, None),
        ("donations", False, "2025-03-02T13:30:00Z", None),
        ("plans", False, "2025-03-02", None),
        ("donors", True, "2025-03-02", None),
    ],
)
def test_incremental_date_filter(
    http_send: MagicMock,
    credentials: DonorboxSourceConfig,
    manager: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: datetime | date | str | None,
    expected: str | None,
) -> None:
    http_send.side_effect = [response([{"id": 1}]), response([])]
    result = source(credentials, manager, endpoint, incremental, watermark)
    rows(result)

    for call in http_send.call_args_list:
        params = parse_qs(urlsplit(call.args[0].url).query)
        assert params.get("date_from") == ([expected] if expected else None)
        assert "date_to" not in params
    if incremental and endpoint in ("donations", "plans"):
        assert result.sort_mode == "desc"
    assert manager.save_state.call_args.args[0].date_from == expected


@pytest.mark.parametrize("saved_date", [None, "2025-01-01"])
def test_resume_keeps_original_filter(
    http_send: MagicMock, credentials: DonorboxSourceConfig, manager: MagicMock, saved_date: str | None
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = DonorboxResumeConfig(page=4, date_from=saved_date)
    http_send.side_effect = [response([{"id": 9}]), response([])]

    assert rows(source(credentials, manager, incremental=True, watermark="2025-03-02")) == [{"id": 9}]
    for page, call in enumerate(http_send.call_args_list, start=4):
        params = parse_qs(urlsplit(call.args[0].url).query)
        assert params["page"] == [str(page)]
        assert params.get("date_from") == ([saved_date] if saved_date else None)
    manager.save_state.assert_called_once_with(DonorboxResumeConfig(page=5, date_from=saved_date))


@pytest.mark.parametrize("has_stale_state", [False, True])
def test_empty_first_page(
    http_send: MagicMock, credentials: DonorboxSourceConfig, manager: MagicMock, has_stale_state: bool
) -> None:
    manager.can_resume.return_value = has_stale_state
    manager.load_state.return_value = None
    http_send.return_value = response([])
    assert rows(source(credentials, manager)) == []
    http_send.assert_called_once()
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, (True, None)),
        (401, (False, "Donorbox authentication failed. Check your organization login email and API key.")),
        (403, (False, "Donorbox denied API access. Enable API & Zapier Integration in your Donorbox account.")),
    ],
)
@pytest.mark.parametrize("schema_name", [None, "plans"])
def test_credential_probe(
    http_send: MagicMock,
    credentials: DonorboxSourceConfig,
    status: int,
    expected: tuple[bool, str | None],
    schema_name: str | None,
) -> None:
    http_send.return_value = response([] if status == 200 else {"error": "Authentication failed"}, status)
    assert validate_credentials(credentials, schema_name) == expected
    http_send.assert_called_once()
    request = http_send.call_args.args[0]
    assert urlsplit(request.url).path == f"/api/v1/{schema_name or 'campaigns'}"
    assert parse_qs(urlsplit(request.url).query) == {"per_page": ["1"]}
    assert b64decode(request.headers["Authorization"].split()[1]).decode() == "warehouse@example.com:test-api-key"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_http_errors_are_not_retried(
    http_send: MagicMock, credentials: DonorboxSourceConfig, manager: MagicMock, status: int
) -> None:
    http_send.return_value = response({"error": "Authentication failed"}, status)
    with pytest.raises(HTTPError) as error:
        rows(source(credentials, manager))
    http_send.assert_called_once()
    matches = [
        message
        for pattern, message in DonorboxSource().get_non_retryable_errors().items()
        if pattern in str(error.value)
    ]
    assert bool(matches) == (status in (401, 403))


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_probe_failures_retry(http_send: MagicMock, credentials: DonorboxSourceConfig, status: int) -> None:
    http_send.side_effect = [response({"error": "temporary"}, status), response([])]
    assert validate_credentials(credentials) == (True, None)
    assert http_send.call_count == 2


def test_unexpected_probe_error_propagates(http_send: MagicMock, credentials: DonorboxSourceConfig) -> None:
    http_send.return_value = response({"error": "missing"}, 404)
    with pytest.raises(HTTPError):
        validate_credentials(credentials)


@pytest.mark.parametrize("probe", [False, True])
def test_unknown_endpoint(
    http_send: MagicMock, credentials: DonorboxSourceConfig, manager: MagicMock, probe: bool
) -> None:
    with pytest.raises(UnknownResourceError):
        if probe:
            validate_credentials(credentials, "unknown")
        else:
            source(credentials, manager, "unknown")
    http_send.assert_not_called()


def test_invalid_success_body_fails(
    http_send: MagicMock, credentials: DonorboxSourceConfig, manager: MagicMock
) -> None:
    http_send.return_value = response({"error": "Authentication failed"})
    with pytest.raises(ValueError, match="Required a list response body"):
        rows(source(credentials, manager))
    manager.save_state.assert_not_called()


@pytest.mark.parametrize(
    "endpoint,field,value,expected",
    [
        ("donations", "donation_date", "2025-03-02T13:30:00Z", datetime(2025, 3, 2, 13, 30, tzinfo=UTC)),
        ("plans", "started_at", "2025-03-02", date(2025, 3, 2)),
    ],
)
def test_dates_and_nested_records(
    http_send: MagicMock,
    credentials: DonorboxSourceConfig,
    manager: MagicMock,
    endpoint: str,
    field: str,
    value: str,
    expected: datetime | date,
) -> None:
    http_send.side_effect = [response([{"id": 1, field: value, "donor": {"id": 7}}]), response([])]
    result = source(credentials, manager, endpoint, incremental=True)
    stream = iter(cast(Iterable[list[dict[str, Any]]], result.items()))

    assert next(stream) == [{"id": 1, field: expected, "donor": {"id": 7}}]
    manager.save_state.assert_not_called()
    assert list(stream) == []
    manager.save_state.assert_called_once_with(DonorboxResumeConfig(page=2))
