import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium import (
    BuildiumResumeConfig,
    buildium_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.source import BuildiumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)

CONFIG = BuildiumSourceConfig(client_id="example-client", client_secret="example-secret")


def response(rows: list[dict[str, Any]], status: int = 200, total: int | None = None) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result._content = json.dumps(rows).encode()
    result.headers["Content-Type"] = "application/json"
    result.url = "https://api.buildium.com/v1/leases"
    if total is not None:
        result.headers["X-Total-Count"] = str(total)
    return result


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def source(
    manager: MagicMock,
    endpoint: str = "leases",
    incremental: bool = False,
    watermark: datetime | str | None = None,
) -> SourceResponse:
    return buildium_source(CONFIG, endpoint, "v1", 1, "test-job", manager, incremental, watermark)


def source_items(result: SourceResponse) -> Iterable[list[dict[str, Any]]]:
    return cast(Iterable[list[dict[str, Any]]], result.items())


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [
        ("rental_properties", "rentals"),
        ("rental_units", "rentals/units"),
        ("leases", "leases"),
        ("tenants", "leases/tenants"),
        ("rental_owners", "rentals/owners"),
        ("vendors", "vendors"),
        ("bills", "bills"),
        ("general_ledger_accounts", "glaccounts"),
        ("work_orders", "workorders"),
        ("applicants", "applicants"),
    ],
)
def test_request_path_and_auth(manager: MagicMock, endpoint: str, path: str) -> None:
    with patch("requests.Session.send", return_value=response([{"Id": 7}])) as send:
        assert list(source_items(source(manager, endpoint))) == [[{"Id": 7}]]
    request: PreparedRequest = send.call_args.args[0]
    assert request.url is not None
    assert urlparse(request.url).path == f"/v1/{path}"
    assert request.headers["x-buildium-client-id"] == "example-client"
    assert request.headers["x-buildium-client-secret"] == "example-secret"
    assert parse_qs(urlparse(request.url).query) == {"limit": ["1000"], "offset": ["0"], "orderby": ["Id asc"]}
    assert send.call_args.kwargs["timeout"] == (10, 30)
    send.assert_called_once()


@pytest.mark.parametrize(
    ("pages", "total", "expected_offsets", "expected_ids"),
    [
        ([[{"Id": 1}, {"Id": 2}], [{"Id": 3}]], 3, ["0", "2"], [1, 2, 3]),
        ([[{"Id": 1}, {"Id": 2}]], 2, ["0"], [1, 2]),
        ([[{"Id": 1}, {"Id": 2}], []], None, ["0", "2"], [1, 2]),
        ([[]], 0, ["0"], []),
    ],
)
def test_pagination(
    manager: MagicMock,
    pages: list[list[dict[str, object]]],
    total: int | None,
    expected_offsets: list[str],
    expected_ids: list[int],
) -> None:
    with (
        patch("products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium.PAGE_SIZE", 2),
        patch("requests.Session.send", side_effect=[response(page, total=total) for page in pages]) as send,
    ):
        iterator = iter(source_items(source(manager)))
        first = next(iterator, [])
        rows = first + [row for page in iterator for row in page]
        if len(expected_offsets) > 1:
            assert manager.save_state.call_args.args[0] == BuildiumResumeConfig(offset=2)
    assert [row["Id"] for row in rows] == expected_ids
    assert [parse_qs(urlparse(call.args[0].url).query)["offset"][0] for call in send.call_args_list] == expected_offsets
    assert manager.save_state.call_count == len(expected_offsets) - 1


@pytest.mark.parametrize("endpoint", ["leases", "applicants"])
@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_filter"),
    [
        (True, None, None),
        (False, "2026-01-02T03:04:05Z", None),
        (True, "2026-01-02T03:04:05.999Z", "2026-01-02T03:04:05Z"),
        (True, datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
        (True, datetime(2026, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2))), "2026-01-02T03:04:05Z"),
    ],
)
def test_incremental_filter_and_timestamp(
    manager: MagicMock, endpoint: str, incremental: bool, watermark: datetime | str | None, expected_filter: str | None
) -> None:
    data: list[dict[str, Any]] = [
        {"Id": 1, "LastUpdatedDateTime": "2026-01-03T00:00:00Z"},
        {"Id": 2, "LastUpdatedDateTime": None},
    ]
    result = source(manager, endpoint, incremental, watermark)
    with patch("requests.Session.send", return_value=response(data)) as send:
        rows = [row for page in source_items(result) for row in page]
    params = parse_qs(urlparse(send.call_args.args[0].url).query)
    assert params.get("lastupdatedfrom") == ([expected_filter] if expected_filter else None)
    assert params["orderby"] == ["Id asc"]
    assert result.sort_mode == "desc"
    assert rows == [
        {"Id": 1, "LastUpdatedDateTime": datetime(2026, 1, 3, tzinfo=UTC)},
        {"Id": 2, "LastUpdatedDateTime": None},
    ]


@pytest.mark.parametrize("original_filter", [None, "2026-01-01T00:00:00Z"])
def test_resume_keeps_filter_and_offset(manager: MagicMock, original_filter: str | None) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = BuildiumResumeConfig(offset=1000, updated_from=original_filter)
    with patch("requests.Session.send", return_value=response([{"Id": 1001}])) as send:
        assert list(source_items(source(manager, incremental=True, watermark="2026-01-05T00:00:00Z"))) == [
            [{"Id": 1001}]
        ]
    params = parse_qs(urlparse(send.call_args.args[0].url).query)
    assert params["offset"] == ["1000"]
    assert params.get("lastupdatedfrom") == ([original_filter] if original_filter else None)


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_mapping(manager: MagicMock, status: int, message: str) -> None:
    with patch("requests.Session.send", return_value=response([], status=status)):
        with pytest.raises(HTTPError) as raised:
            list(source_items(source(manager)))
    errors = BuildiumSource().get_non_retryable_errors()
    assert next(value for key, value in errors.items() if key in str(raised.value)) == message
