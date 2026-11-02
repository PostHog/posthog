from base64 import b64decode
from datetime import UTC, date, datetime

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.donorbox import (
    DonorboxResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.source import DonorboxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.donorbox import (
    DonorboxSourceConfig,
)


@pytest.fixture
def credentials() -> DonorboxSourceConfig:
    return DonorboxSourceConfig(email="warehouse@example.com", api_key="test-api-key")


@pytest.fixture
def driver(credentials: DonorboxSourceConfig) -> SourceDriver:
    return SourceDriver(DonorboxSource(), credentials)


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
    driver: SourceDriver,
    endpoint: str,
    incremental: bool,
    watermark: datetime | date | str | None,
    expected: str | None,
) -> None:
    result = driver.run(
        endpoint,
        [ScriptedResponse(json=[{"id": 1}]), ScriptedResponse(json=[])],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    for request in result.requests:
        assert request.param("date_from") == expected
        assert request.param("date_to") is None
    if incremental and endpoint in ("donations", "plans"):
        assert result.response is not None
        assert result.response.sort_mode == "desc"
    assert result.saved_states[-1].date_from == expected


@pytest.mark.parametrize("saved_date", [None, "2025-01-01"])
def test_resume_keeps_original_filter(driver: SourceDriver, saved_date: str | None) -> None:
    result = driver.run(
        "donations",
        [ScriptedResponse(json=[{"id": 9}]), ScriptedResponse(json=[])],
        resume_state=DonorboxResumeConfig(page=4, date_from=saved_date),
        should_use_incremental_field=True,
        db_incremental_field_last_value="2025-03-02",
    )

    assert result.raised is None
    assert result.rows == [{"id": 9}]
    assert result.params("page") == ["4", "5"]
    assert result.params("date_from") == [saved_date, saved_date]
    assert result.saved_states == [DonorboxResumeConfig(page=5, date_from=saved_date)]


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
    credentials: DonorboxSourceConfig,
    status: int,
    expected: tuple[bool, str | None],
    schema_name: str | None,
) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json=[] if status == 200 else {"error": "Authentication failed"})]
    ) as network:
        assert validate_credentials(credentials, schema_name) == expected

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == f"/api/v1/{schema_name or 'campaigns'}"
    assert request.query == {"per_page": ("1",)}
    assert b64decode(request.headers["authorization"].split()[1]).decode() == "warehouse@example.com:test-api-key"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_http_errors_are_not_retried(driver: SourceDriver, status: int) -> None:
    result = driver.run("donations", [ScriptedResponse(status=status, json={"error": "Authentication failed"})])

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    matches = [
        message
        for pattern, message in DonorboxSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert bool(matches) == (status in (401, 403))


def test_unexpected_probe_error_propagates(credentials: DonorboxSourceConfig) -> None:
    with scripted_network([ScriptedResponse(status=404, json={"error": "missing"})]):
        with pytest.raises(HTTPError):
            validate_credentials(credentials)


@pytest.mark.parametrize("probe", [False, True])
def test_unknown_endpoint(driver: SourceDriver, credentials: DonorboxSourceConfig, probe: bool) -> None:
    if probe:
        with scripted_network([]) as network:
            with pytest.raises(UnknownResourceError):
                validate_credentials(credentials, "unknown")
        assert network.requests_log == []
    else:
        result = driver.run("unknown", [])
        assert isinstance(result.raised, UnknownResourceError)
        assert result.requests == []


def test_invalid_success_body_fails(driver: SourceDriver) -> None:
    result = driver.run("donations", [ScriptedResponse(json={"error": "Authentication failed"})])

    assert isinstance(result.raised, ValueError)
    assert "Required a list response body" in str(result.raised)
    assert result.saved_states == []


@pytest.mark.parametrize(
    "endpoint,field,value,expected",
    [
        ("donations", "donation_date", "2025-03-02T13:30:00Z", datetime(2025, 3, 2, 13, 30, tzinfo=UTC)),
        ("plans", "started_at", "2025-03-02", date(2025, 3, 2)),
    ],
)
def test_dates_and_nested_records(
    driver: SourceDriver,
    endpoint: str,
    field: str,
    value: str,
    expected: datetime | date,
) -> None:
    result = driver.run(
        endpoint,
        [ScriptedResponse(json=[{"id": 1, field: value, "donor": {"id": 7}}]), ScriptedResponse(json=[])],
        should_use_incremental_field=True,
    )

    assert result.raised is None
    assert result.items == [[{"id": 1, field: expected, "donor": {"id": 7}}]]
    assert result.committed_states == [DonorboxResumeConfig(page=2)]
    assert result.saved_states == [DonorboxResumeConfig(page=2)]
