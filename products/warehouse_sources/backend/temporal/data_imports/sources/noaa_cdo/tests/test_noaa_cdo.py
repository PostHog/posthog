from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests_mock
from requests import Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.noaacdo import (
    NoaaCdoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.noaa_cdo import (
    NoaaCdoResumeConfig,
    noaa_cdo_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.settings import AUTH_ERROR, REQUEST_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.source import NoaaCdoSource


def sync_items(response: SourceResponse) -> Iterable[Any]:
    items = response.items()
    assert isinstance(items, Iterable)
    return items


@pytest.fixture(autouse=True)
def fixed_clock() -> Iterator[None]:
    with time_machine.travel("2024-01-03T12:00:00Z", tick=False):
        yield


@pytest.fixture
def http() -> Iterator[requests_mock.Mocker]:
    with (
        requests_mock.Mocker() as mock,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            side_effect=lambda **kwargs: Session(),
        ),
    ):
        yield mock


@pytest.fixture
def config() -> NoaaCdoSourceConfig:
    return NoaaCdoSourceConfig(
        api_token="test-noaa-token", dataset_id="GHCND", station_id="GHCND:TEST0001", start_date="2024-01-01"
    )


@pytest.fixture
def manager() -> MagicMock:
    mock = MagicMock(spec=ResumableSourceManager)
    mock.can_resume.return_value = False
    return mock


@pytest.mark.parametrize("count", [0, 1, 1000, 1001, 2000])
def test_offset_pagination_and_terminal_page(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, manager: MagicMock, count: int
) -> None:
    rows = [{"id": f"station-{i}"} for i in range(count)]

    def page(request: Any, context: Any) -> dict[str, Any]:
        offset = int(request.qs["offset"][0])
        return {
            "results": rows[offset - 1 : offset + 999],
            "metadata": {"resultset": {"count": count, "offset": offset, "limit": 1000}},
        }

    http.get("https://www.ncei.noaa.gov/cdo-web/api/v2/stations", json=page)
    result = noaa_cdo_source(config, "stations", 1, "test", manager, "v2")
    actual = [row for batch in sync_items(result) for row in batch]

    assert actual == rows
    assert [r.qs["offset"] for r in http.request_history] == [[str(i)] for i in range(1, count + 2, 1000)]
    assert all(r.headers["token"] == "test-noaa-token" for r in http.request_history)
    assert all("token" not in r.qs and r.qs["limit"] == ["1000"] for r in http.request_history)
    assert manager.save_state.call_args.args[0].complete


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("datasets", {"stationid": ["ghcnd:test0001"]}),
        ("stations", {"datasetid": ["ghcnd"]}),
        ("datatypes", {"datasetid": ["ghcnd"], "stationid": ["ghcnd:test0001"]}),
        ("datacategories", {"datasetid": ["ghcnd"], "stationid": ["ghcnd:test0001"]}),
        ("locations", {"datasetid": ["ghcnd"]}),
        ("locationcategories", {"datasetid": ["ghcnd"]}),
    ],
)
def test_reference_table_filters(
    http: requests_mock.Mocker,
    config: NoaaCdoSourceConfig,
    manager: MagicMock,
    endpoint: str,
    expected: dict[str, list[str]],
) -> None:
    http.get(f"https://www.ncei.noaa.gov/cdo-web/api/v2/{endpoint}", json={"results": [{"id": "test"}]})
    list(sync_items(noaa_cdo_source(config, endpoint, 1, "test", manager, "v2", True, "2024-01-02")))
    assert http.last_request is not None
    assert http.last_request.qs == {
        **expected,
        "sortfield": ["id"],
        "sortorder": ["asc"],
        "limit": ["1000"],
        "offset": ["1"],
    }


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_start"),
    [
        (False, "2024-01-02T00:00:00Z", "2023-12-01"),
        (True, None, "2023-12-01"),
        (True, "2024-01-02T00:00:00Z", "2023-12-26"),
        (True, datetime(2024, 1, 2, tzinfo=UTC), "2023-12-26"),
        (True, date(2024, 1, 2), "2023-12-26"),
        (True, "2023-12-02", "2023-12-01"),
    ],
)
def test_observation_date_filters(
    http: requests_mock.Mocker,
    config: NoaaCdoSourceConfig,
    manager: MagicMock,
    incremental: bool,
    watermark: str | date | datetime | None,
    expected_start: str,
) -> None:
    config.start_date = "2023-12-01"
    row = {"date": "2024-01-02T00:00:00", "station": "GHCND:TEST0001", "datatype": "TMAX", "value": 10}
    http.get("https://www.ncei.noaa.gov/cdo-web/api/v2/data", json={"results": [row]})
    result = noaa_cdo_source(config, "data", 1, "test", manager, "v2", incremental, watermark)
    assert list(sync_items(result)) == [[row]]
    assert result.sort_mode == "desc"
    assert http.last_request is not None
    assert http.last_request.qs == {
        "datasetid": ["ghcnd"],
        "stationid": ["ghcnd:test0001"],
        "startdate": [expected_start],
        "enddate": ["2024-01-03"],
        "units": ["metric"],
        "offset": ["1"],
        "limit": ["1000"],
    }


@pytest.mark.parametrize("empty_body", [{}, {"results": []}])
def test_date_windows_continue_after_empty_results(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, manager: MagicMock, empty_body: dict[str, Any]
) -> None:
    config.start_date = "2020-01-01"
    http.get("https://www.ncei.noaa.gov/cdo-web/api/v2/data", json=empty_body)
    assert list(sync_items(noaa_cdo_source(config, "data", 1, "test", manager, "v2"))) == []
    assert [(r.qs["startdate"][0], r.qs["enddate"][0]) for r in http.request_history] == [
        ("2020-01-01", "2020-12-30"),
        ("2020-12-31", "2021-12-30"),
        ("2021-12-31", "2022-12-30"),
        ("2022-12-31", "2023-12-30"),
        ("2023-12-31", "2024-01-03"),
    ]
    assert manager.safe_point.call_count == 5
    assert manager.save_state.call_args.args[0].complete


@pytest.mark.parametrize("endpoint", ["data", "stations"])
def test_resume_starts_at_saved_offset_and_preserves_window(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, manager: MagicMock, endpoint: str
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = NoaaCdoResumeConfig(offset=1001, window_start="2024-01-02", end_date="2024-01-02")
    http.get(f"https://www.ncei.noaa.gov/cdo-web/api/v2/{endpoint}", json={"results": [{"id": "last"}]})
    assert list(sync_items(noaa_cdo_source(config, endpoint, 1, "test", manager, "v2"))) == [[{"id": "last"}]]
    assert http.last_request is not None
    assert http.last_request.qs["offset"] == ["1001"]
    if endpoint == "data":
        assert http.last_request.qs["startdate"] == ["2024-01-02"]
        assert http.last_request.qs["enddate"] == ["2024-01-02"]
    assert manager.save_state.call_args.args[0].complete


def test_completed_resume_makes_no_requests(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = NoaaCdoResumeConfig(complete=True)
    assert list(sync_items(noaa_cdo_source(config, "data", 1, "test", manager, "v2"))) == []
    assert not http.called


def test_resume_after_page_failure_then_advance_to_next_window(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, manager: MagicMock
) -> None:
    config.start_date = "2023-01-01"
    rows = [
        {"station": "GHCND:TEST0001", "datatype": f"TYPE{i}", "date": "2023-01-01T00:00:00", "value": i}
        for i in range(1000)
    ]
    url = "https://www.ncei.noaa.gov/cdo-web/api/v2/data"
    http.get(
        url,
        [
            {"json": {"results": rows}},
            {"status_code": 400, "json": {"message": "The token parameter provided is not valid."}},
        ],
    )
    pages = iter(sync_items(noaa_cdo_source(config, "data", 1, "test", manager, "v2")))
    assert next(pages) == rows
    with pytest.raises(ValueError, match=AUTH_ERROR):
        next(pages)
    checkpoint = manager.save_state.call_args.args[0]
    assert checkpoint.offset == 1001
    assert checkpoint.window_start == "2023-01-01"
    assert not checkpoint.complete

    manager.can_resume.return_value = True
    manager.load_state.return_value = checkpoint
    http.get(
        url,
        json={
            "results": [{"station": "GHCND:TEST0001", "datatype": "PRCP", "date": "2023-12-31T00:00:00", "value": 1}]
        },
    )
    batches = list(sync_items(noaa_cdo_source(config, "data", 1, "test", manager, "v2")))
    assert len(batches) == 2
    assert [(r.qs["startdate"], r.qs["offset"]) for r in http.request_history[2:]] == [
        (["2023-01-01"], ["1001"]),
        (["2024-01-01"], ["1"]),
    ]
    assert manager.save_state.call_args.args[0].complete


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (400, "Token parameter is required.", AUTH_ERROR),
        (400, "The token parameter provided is not valid.", AUTH_ERROR),
        (401, "Unauthorized", AUTH_ERROR),
        (403, "Forbidden", AUTH_ERROR),
        (400, "Invalid dataset", REQUEST_ERROR),
    ],
)
def test_authentication_and_request_errors(
    http: requests_mock.Mocker,
    config: NoaaCdoSourceConfig,
    manager: MagicMock,
    status: int,
    message: str,
    expected: str,
) -> None:
    http.get(requests_mock.ANY, status_code=status, json={"status": str(status), "message": message})
    source = NoaaCdoSource()
    assert source.validate_credentials(config, 1) == (False, expected)
    assert http.call_count == 1
    with pytest.raises(ValueError, match=expected):
        list(sync_items(noaa_cdo_source(config, "data", 1, "test", manager, "v2")))
    assert http.call_count == 2
    assert source.get_non_retryable_errors()[expected] == expected


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry_without_invalidating_credentials(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, status: int
) -> None:
    http.get(
        "https://www.ncei.noaa.gov/cdo-web/api/v2/datasets",
        [
            {"status_code": status, "json": {}, "headers": {"Retry-After": "0"}},
            {"json": {"results": [{"id": "GHCND"}]}},
        ],
    )
    assert NoaaCdoSource().validate_credentials(config, 1) == (True, None)
    assert http.call_count == 2
    assert http.last_request is not None
    assert http.last_request.qs == {"limit": ["1"]}
    assert http.last_request.headers["token"] == config.api_token


@pytest.mark.parametrize("body", [{"message": "unexpected failure"}, {"metadata": {"resultset": {"count": 1}}}])
def test_unexpected_response_fails_without_saving_completion(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, manager: MagicMock, body: dict[str, Any]
) -> None:
    http.get(requests_mock.ANY, json=body)
    with pytest.raises(ValueError, match="Required data_selector"):
        list(sync_items(noaa_cdo_source(config, "data", 1, "test", manager, "v2")))
    manager.save_state.assert_not_called()
    with pytest.raises(ValueError, match="Required data_selector"):
        NoaaCdoSource().validate_credentials(config, 1)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("start_date", "invalid", "Enter the start date as YYYY-MM-DD."),
        ("start_date", "20240101", "Enter the start date as YYYY-MM-DD."),
        ("start_date", "2024-01-04", "The start date must be today or earlier."),
        ("dataset_id", " ", "Enter one dataset ID and one station ID."),
        ("station_id", "", "Enter one dataset ID and one station ID."),
    ],
)
def test_invalid_configuration_stops_before_network(
    http: requests_mock.Mocker, config: NoaaCdoSourceConfig, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    assert NoaaCdoSource().validate_credentials(config, 1) == (False, message)
    assert not http.called


def test_unknown_endpoint_cannot_change_request_path(config: NoaaCdoSourceConfig, manager: MagicMock) -> None:
    with pytest.raises(ValueError, match="Unknown NOAA table"):
        noaa_cdo_source(config, "https://example.com", 1, "test", manager, "v2")
