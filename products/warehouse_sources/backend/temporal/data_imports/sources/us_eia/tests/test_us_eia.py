from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import structlog
import requests_mock
from requests.exceptions import HTTPError, Timeout

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.source import UsEiaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.us_eia import (
    EiaResumeConfig,
    us_eia_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="electricity_retail_sales",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=True,
        db_incremental_field_last_value=datetime(2025, 1, 15, tzinfo=UTC),
        db_incremental_field_earliest_value=None,
        incremental_field="period",
        incremental_field_type=IncrementalFieldType.DateTime,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.mark.parametrize("terminal_rows", [0, 1])
def test_pagination_and_checkpoint(
    inputs: SourceInputs,
    manager: MagicMock,
    terminal_rows: int,
) -> None:
    rows = [{"period": "2025-01", "stateid": f"area-{i}", "sectorid": "RES"} for i in range(5000)]
    with requests_mock.Mocker() as http:
        http.get(
            "https://api.eia.gov/v2/electricity/retail-sales/data/",
            [
                {"json": {"response": {"total": str(5000 + terminal_rows), "data": rows}}},
                {"json": {"response": {"total": str(5000 + terminal_rows), "data": rows[:terminal_rows]}}},
            ],
        )
        resource = iter(cast(Iterable[Any], us_eia_source("example-key", inputs, manager).items()))
        assert len(next(resource)) == 5000
        assert sum(len(page) for page in resource) == terminal_rows
        manager.save_state.assert_called_once_with(EiaResumeConfig(offset=5000, start="2025-01"))
        manager.clear_state.assert_called_once_with()
        assert [request.qs["offset"] for request in http.request_history] == [["0"], ["5000"]]
        assert all(request.qs["start"] == ["2025-01"] for request in http.request_history)


@pytest.mark.parametrize("saved_start", [None, "2024-01"])
def test_resume_preserves_original_range(inputs: SourceInputs, manager: MagicMock, saved_start: str | None) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = EiaResumeConfig(offset=10000, start=saved_start)
    with requests_mock.Mocker() as http:
        http.get(
            "https://api.eia.gov/v2/electricity/retail-sales/data/",
            json={"response": {"total": "10000", "data": []}},
        )
        list(cast(Iterable[Any], us_eia_source("example-key", inputs, manager).items()))
        assert http.last_request is not None
        assert http.last_request.qs["offset"] == ["10000"]
        assert http.last_request.qs.get("start") == ([saved_start] if saved_start else None)


@pytest.mark.parametrize("watermark", ["2025-01-15T00:00:00+00:00", "2025-01-15"])
def test_string_watermark(inputs: SourceInputs, manager: MagicMock, watermark: str) -> None:
    inputs.db_incremental_field_last_value = watermark
    inputs.schema_name = "retail_fuel_prices"
    with requests_mock.Mocker() as http:
        http.get("https://api.eia.gov/v2/petroleum/pri/gnd/data/", json={"response": {"data": []}})
        list(cast(Iterable[Any], us_eia_source("example-key", inputs, manager).items()))
        assert http.last_request is not None
        assert http.last_request.qs["start"] == ["2025-01-15"]


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, (True, None)),
        (401, (False, "EIA rejected the API key. Check your key. If EIA suspended it, wait before trying again.")),
        (403, (False, "EIA rejected the API key. Check your key. If EIA suspended it, wait before trying again.")),
        (429, (False, "Could not validate the EIA API key. Try again later.")),
        (500, (False, "Could not validate the EIA API key. Try again later.")),
    ],
)
def test_validation(status: int, expected: tuple[bool, str | None]) -> None:
    with requests_mock.Mocker() as http:
        http.get("https://api.eia.gov/v2/electricity/retail-sales/", status_code=status, json={})
        assert validate_credentials("example-key") == expected
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.qs == {"api_key": ["example-key"]}
        assert "Authorization" not in http.last_request.headers


def test_validation_timeout() -> None:
    with requests_mock.Mocker() as http:
        http.get("https://api.eia.gov/v2/electricity/retail-sales/", exc=Timeout)
        assert validate_credentials("example-key") == (False, "Could not connect to EIA. Try again later.")


@pytest.mark.parametrize("status,code", [(401, "API_KEY_INVALID"), (403, "API_KEY_MISSING")])
def test_sync_auth_errors_are_safe_and_not_retried(
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
    code: str,
) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            "https://api.eia.gov/v2/electricity/retail-sales/data/",
            status_code=status,
            reason="Unauthorized" if status == 401 else "Forbidden",
            json={"error": {"code": code}},
        )
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], us_eia_source("example-key", inputs, manager).items()))
        assert http.call_count == 1
        assert "example-key" not in str(error.value)
        assert any(pattern in str(error.value) for pattern in UsEiaSource().get_non_retryable_errors())


@pytest.mark.parametrize(
    "schema,field,error,match",
    [
        ("missing", "period", UnknownResourceError, "This table is not available"),
        ("electricity_retail_sales", "value", ValueError, "only by period"),
    ],
)
def test_invalid_schema_or_cursor(
    inputs: SourceInputs,
    manager: MagicMock,
    schema: str,
    field: str,
    error: type[Exception],
    match: str,
) -> None:
    inputs.schema_name = schema
    inputs.incremental_field = field
    with pytest.raises(error, match=match):
        us_eia_source("example-key", inputs, manager)
