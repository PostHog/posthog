from datetime import UTC, datetime

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevenshifts import (
    SevenShiftsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.sevenshifts import (
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.source import SevenShiftsSource


@pytest.fixture
def config() -> SevenShiftsSourceConfig:
    return SevenShiftsSourceConfig(access_token="test-access-token", company_id="123")


@pytest.fixture
def driver(config: SevenShiftsSourceConfig) -> SourceDriver:
    return SourceDriver(SevenShiftsSource(), config)


def response(rows: list[dict[str, object]], cursor: str | None = None, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"data": rows, "meta": {"cursor": {"next": cursor}}})


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
    driver: SourceDriver,
    endpoint: str,
    watermark: str | datetime,
    expected: str,
    incremental: bool,
) -> None:
    result = driver.run(
        endpoint,
        [response([{"id": 1}], "page-two"), response([])],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert len(result.requests) == 2
    assert result.params("modified_since") == ([expected] * 2 if incremental else [None] * 2)


def test_repeated_cursor_fails(driver: SourceDriver) -> None:
    result = driver.run("users", [response([{"id": 1}], "same-cursor"), response([{"id": 1}], "same-cursor")])

    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)


def test_missing_data_fails(driver: SourceDriver) -> None:
    result = driver.run("users", [ScriptedResponse(body=b'{"unexpected": []}')])

    assert isinstance(result.raised, ValueError)
    assert "data_selector" in str(result.raised)


@pytest.mark.parametrize("company_id", ["", "abc", "0", "-1", "123/../users", "１２３"])
def test_invalid_company_id_stops_before_request(config: SevenShiftsSourceConfig, company_id: str) -> None:
    config.company_id = company_id
    with scripted_network([]) as network:
        assert validate_credentials(config, "2026-01-01") == (False, "Enter a positive numeric 7shifts company ID.")

    assert network.requests_log == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, (False, "7shifts could not find this company. Check the company ID.")),
    ],
)
def test_credential_probe(config: SevenShiftsSourceConfig, status: int, expected: tuple[bool, str | None]) -> None:
    with scripted_network([response([], "unused-next-page", status=status)]) as network:
        assert validate_credentials(config, "2026-01-01") == expected

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == "https://api.7shifts.com/v2/company/123/locations?limit=1"
    assert request.headers["authorization"] == "Bearer test-access-token"
    assert request.headers["x-api-version"] == "2026-01-01"


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_error_classification(driver: SourceDriver, status: int) -> None:
    result = driver.run("users", always(response([], status=status)))

    error_type = RESTClientRetryableError if status in (429, 500) else HTTPError
    assert isinstance(result.raised, error_type)
    patterns = SevenShiftsSource().get_non_retryable_errors()
    assert any(pattern in str(result.raised) for pattern in patterns) == (status in (401, 403))


def test_unexpected_probe_error_propagates(config: SevenShiftsSourceConfig) -> None:
    with scripted_network([response([], status=400)]):
        with pytest.raises(HTTPError):
            validate_credentials(config, "2026-01-01")
