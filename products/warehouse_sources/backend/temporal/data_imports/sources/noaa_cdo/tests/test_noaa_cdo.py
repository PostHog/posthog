from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.noaacdo import (
    NoaaCdoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.settings import AUTH_ERROR, REQUEST_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.source import NoaaCdoSource


@pytest.fixture(autouse=True)
def fixed_clock() -> Iterator[None]:
    with time_machine.travel("2024-01-03T12:00:00Z", tick=False):
        yield


@pytest.fixture
def config() -> NoaaCdoSourceConfig:
    return NoaaCdoSourceConfig(
        api_token="test-noaa-token", dataset_id="GHCND", station_id="GHCND:TEST0001", start_date="2024-01-01"
    )


@pytest.mark.parametrize("count", [0, 1, 1000, 1001, 2000])
def test_offset_pagination_and_terminal_page(config: NoaaCdoSourceConfig, count: int) -> None:
    rows = [{"id": f"station-{i}"} for i in range(count)]
    offsets = range(1, count + 2, 1000)
    script = [
        ScriptedResponse(
            json={
                "results": rows[offset - 1 : offset + 999],
                "metadata": {"resultset": {"count": count, "offset": offset, "limit": 1000}},
            }
        )
        for offset in offsets
    ]

    result = SourceDriver(NoaaCdoSource(), config).run("stations", script)

    assert result.raised is None
    assert result.rows == rows
    assert result.params("offset") == [str(offset) for offset in offsets]
    assert all(request.headers["token"] == "test-noaa-token" for request in result.requests)
    assert all(request.param("token") is None and request.param("limit") == "1000" for request in result.requests)
    assert result.saved_states[-1].complete


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
    config: NoaaCdoSourceConfig,
    incremental: bool,
    watermark: str | date | datetime | None,
    expected_start: str,
) -> None:
    config.start_date = "2023-12-01"
    row = {"date": "2024-01-02T00:00:00", "station": "GHCND:TEST0001", "datatype": "TMAX", "value": 10}
    result = SourceDriver(NoaaCdoSource(), config).run(
        "data",
        [ScriptedResponse(json={"results": [row]})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.items == [[row]]
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.queries == [
        {
            "datasetid": ("GHCND",),
            "stationid": ("GHCND:TEST0001",),
            "startdate": (expected_start,),
            "enddate": ("2024-01-03",),
            "units": ("metric",),
            "offset": ("1",),
            "limit": ("1000",),
        }
    ]


def test_resume_after_page_failure_then_advance_to_next_window(config: NoaaCdoSourceConfig) -> None:
    config.start_date = "2023-01-01"
    rows = [
        {"station": "GHCND:TEST0001", "datatype": f"TYPE{i}", "date": "2023-01-01T00:00:00", "value": i}
        for i in range(1000)
    ]
    driver = SourceDriver(NoaaCdoSource(), config)
    first = driver.run(
        "data",
        [
            ScriptedResponse(json={"results": rows}),
            ScriptedResponse(status=400, json={"message": "The token parameter provided is not valid."}),
        ],
    )

    assert first.items == [rows]
    assert isinstance(first.raised, ValueError)
    assert AUTH_ERROR in str(first.raised)
    checkpoint = first.saved_states[-1]
    assert checkpoint.offset == 1001
    assert checkpoint.window_start == "2023-01-01"
    assert not checkpoint.complete
    assert first.final_state == checkpoint

    row = {"station": "GHCND:TEST0001", "datatype": "PRCP", "date": "2023-12-31T00:00:00", "value": 1}
    resumed = driver.run(
        "data",
        [ScriptedResponse(json={"results": [row]}), ScriptedResponse(json={"results": [row]})],
        resume_state=checkpoint,
    )

    assert resumed.raised is None
    assert resumed.items == [[row], [row]]
    assert list(zip(resumed.params("startdate"), resumed.params("offset"))) == [
        ("2023-01-01", "1001"),
        ("2024-01-01", "1"),
    ]
    assert resumed.saved_states[-1].complete


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (400, "Token parameter is required.", AUTH_ERROR),
        (400, "The token parameter provided is not valid.", AUTH_ERROR),
        (400, "Invalid dataset", REQUEST_ERROR),
    ],
)
def test_authentication_and_request_errors(
    config: NoaaCdoSourceConfig,
    status: int,
    message: str,
    expected: str,
) -> None:
    response = ScriptedResponse(status=status, json={"status": str(status), "message": message})
    source = NoaaCdoSource()
    with scripted_network([response]) as network:
        assert source.validate_credentials(config, 1) == (False, expected)
    assert len(network.requests_log) == 1

    result = SourceDriver(source, config).run("data", [response])
    assert isinstance(result.raised, ValueError)
    assert expected in str(result.raised)
    assert len(result.requests) == 1
    assert source.get_non_retryable_errors()[expected] == expected


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry_without_invalidating_credentials(config: NoaaCdoSourceConfig, status: int) -> None:
    with scripted_network(
        [
            ScriptedResponse(status=status, json={}, headers={"Retry-After": "0"}),
            ScriptedResponse(json={"results": [{"id": "GHCND"}]}),
        ]
    ) as network:
        assert NoaaCdoSource().validate_credentials(config, 1) == (True, None)

    assert len(network.requests_log) == 2
    assert network.requests_log[-1].param("limit") == "1"
    assert network.requests_log[-1].headers["token"] == config.api_token


@pytest.mark.parametrize("body", [{"message": "unexpected failure"}, {"metadata": {"resultset": {"count": 1}}}])
def test_unexpected_response_fails_without_saving_completion(config: NoaaCdoSourceConfig, body: dict[str, Any]) -> None:
    response = ScriptedResponse(json=body)
    result = SourceDriver(NoaaCdoSource(), config).run("data", [response])

    assert isinstance(result.raised, ValueError)
    assert "Required data_selector" in str(result.raised)
    assert result.saved_states == []
    with scripted_network([response]):
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
    config: NoaaCdoSourceConfig, field: str, value: str, message: str
) -> None:
    setattr(config, field, value)
    with scripted_network([]) as network:
        assert NoaaCdoSource().validate_credentials(config, 1) == (False, message)
    assert network.requests_log == []


def test_unknown_endpoint_cannot_change_request_path(config: NoaaCdoSourceConfig) -> None:
    result = SourceDriver(NoaaCdoSource(), config).run("https://example.com", [])

    assert isinstance(result.raised, ValueError)
    assert "Unknown NOAA table" in str(result.raised)
    assert result.requests == []
