from datetime import UTC, datetime
from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.useia import UsEiaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.source import UsEiaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.us_eia import (
    EiaResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

INCREMENTAL: dict[str, Any] = {
    "incremental_field": "period",
    "incremental_field_type": IncrementalFieldType.DateTime,
    "db_incremental_field_last_value": datetime(2025, 1, 15, tzinfo=UTC),
}


def _driver() -> SourceDriver:
    return SourceDriver(UsEiaSource(), UsEiaSourceConfig(api_key="example-key"))


@pytest.mark.parametrize("terminal_rows", [0, 1])
def test_pagination_and_checkpoint(terminal_rows: int) -> None:
    rows = [{"period": "2025-01", "stateid": f"area-{i}", "sectorid": "RES"} for i in range(5000)]
    result = _driver().run(
        "electricity_retail_sales",
        [
            ScriptedResponse(json={"response": {"total": str(5000 + terminal_rows), "data": rows}}),
            ScriptedResponse(json={"response": {"total": str(5000 + terminal_rows), "data": rows[:terminal_rows]}}),
        ],
        **INCREMENTAL,
    )

    assert result.raised is None
    assert len(result.items[0]) == 5000
    assert sum(len(page) for page in result.items[1:]) == terminal_rows
    assert result.saved_states == [EiaResumeConfig(offset=5000, start="2025-01")]
    assert result.final_state is None
    assert result.params("offset") == ["0", "5000"]
    assert result.params("start") == ["2025-01"] * 2


@pytest.mark.parametrize("saved_start", [None, "2024-01"])
def test_resume_preserves_original_range(saved_start: str | None) -> None:
    result = _driver().run(
        "electricity_retail_sales",
        [ScriptedResponse(json={"response": {"total": "10000", "data": []}})],
        resume_state=EiaResumeConfig(offset=10000, start=saved_start),
        **INCREMENTAL,
    )

    assert result.params("offset") == ["10000"]
    assert result.params("start") == [saved_start]


def test_a_run_with_no_saved_state_starts_from_the_first_page() -> None:
    result = _driver().run(
        "electricity_retail_sales",
        [ScriptedResponse(json={"response": {"total": "0", "data": []}})],
        **INCREMENTAL,
    )

    assert result.params("offset") == ["0"]


@pytest.mark.parametrize("watermark", ["2025-01-15T00:00:00+00:00", "2025-01-15"])
def test_string_watermark(watermark: str) -> None:
    result = _driver().run(
        "retail_fuel_prices",
        [ScriptedResponse(json={"response": {"data": []}})],
        **{**INCREMENTAL, "db_incremental_field_last_value": watermark},
    )

    assert result.paths == ["/v2/petroleum/pri/gnd/data/"]
    assert result.params("start") == ["2025-01-15"]


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, (False, "Could not validate the EIA API key. Try again later.")),
    ],
)
def test_validation(status: int, expected: tuple[bool, str | None]) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
        assert validate_credentials("example-key") == expected

    assert {request.path for request in network.requests_log} == {"/v2/electricity/retail-sales/"}
    first = network.requests_log[0]
    assert dict(first.query) == {"api_key": ("example-key",)}
    assert "authorization" not in first.headers


def test_validation_timeout() -> None:
    with scripted_network(always(TimeoutError("timed out"))):
        assert validate_credentials("example-key") == (False, "Could not connect to EIA. Try again later.")


@pytest.mark.parametrize("status,code", [(401, "API_KEY_INVALID"), (403, "API_KEY_MISSING")])
def test_sync_auth_errors_are_safe_and_not_retried(status: int, code: str) -> None:
    result = _driver().run(
        "electricity_retail_sales",
        always(ScriptedResponse(status=status, json={"error": {"code": code}})),
        **INCREMENTAL,
    )

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    assert "example-key" not in str(result.raised)
    assert any(pattern in str(result.raised) for pattern in UsEiaSource().get_non_retryable_errors())


@pytest.mark.parametrize(
    "schema,field,error,match",
    [
        ("missing", "period", UnknownResourceError, "This table is not available"),
        ("electricity_retail_sales", "value", ValueError, "only by period"),
    ],
)
def test_invalid_schema_or_cursor(schema: str, field: str, error: type[Exception], match: str) -> None:
    result = _driver().run(schema, [], **{**INCREMENTAL, "incremental_field": field})

    assert isinstance(result.raised, error)
    assert match in str(result.raised)
    assert result.requests == []
