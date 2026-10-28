from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ustreasuryfiscaldata import (
    UsTreasuryFiscalDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.source import (
    UsTreasuryFiscalDataSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.us_treasury_fiscal_data import (
    FiscalDataResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def run(
    name: str = "debt_to_penny",
    script: Script = (),
    *,
    incremental: bool = True,
    watermark: date | str | None = None,
    resume_state: FiscalDataResumeConfig | None = None,
) -> DriveResult:
    driver = SourceDriver(UsTreasuryFiscalDataSource(), UsTreasuryFiscalDataSourceConfig())
    incremental_inputs = (
        {
            "incremental_field": "effective_date" if name == "rates_of_exchange" else "record_date",
            "incremental_field_type": IncrementalFieldType.Date,
        }
        if incremental
        else {}
    )
    return driver.run(
        name,
        script,
        resume_state=resume_state,
        db_incremental_field_last_value=watermark,
        **incremental_inputs,
    )


@pytest.mark.parametrize(
    ("name", "path", "cursor", "numeric_field"),
    [
        ("debt_to_penny", "v2/accounting/od/debt_to_penny", "record_date", "tot_pub_debt_out_amt"),
        ("avg_interest_rates", "v2/accounting/od/avg_interest_rates", "record_date", "avg_interest_rate_amt"),
        ("rates_of_exchange", "v1/accounting/od/rates_of_exchange", "effective_date", "exchange_rate"),
    ],
)
@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_filter"),
    [
        (False, "2025-03-31", None),
        (True, None, None),
        (True, "2025-03-31T12:30:00Z", "2025-03-31"),
        (True, date(2025, 3, 31), "2025-03-31"),
        (True, datetime(2025, 3, 31, 12, 30, tzinfo=UTC), "2025-03-31"),
    ],
)
def test_requests_pagination_and_normalization(
    name: str,
    path: str,
    cursor: str,
    numeric_field: str,
    incremental: bool,
    watermark: date | str | None,
    expected_filter: str | None,
) -> None:
    rows = [
        {
            "record_date": "2025-03-31",
            "effective_date": "2025-04-15",
            "src_line_nbr": "7",
            numeric_field: "12345678901234.56",
        },
        {"record_date": "2025-06-30", "effective_date": "2025-06-30", "src_line_nbr": "8", numeric_field: "null"},
    ]

    result = run(
        name,
        [ScriptedResponse(json={"data": [row], "meta": {"total-pages": 2}}) for row in rows],
        incremental=incremental,
        watermark=watermark,
    )

    assert result.raised is None
    assert len(result.requests) == 2
    for page, request in enumerate(result.requests, 1):
        assert request.path == "/services/api/fiscal_service/" + path
        assert request.param("page[number]") == str(page)
        assert request.param("page[size]") == "1000"
        assert (request.param("sort") or "").split(",")[0] == cursor
        assert request.param("filter") == (f"{cursor}:gte:{expected_filter}" if expected_filter else None)
        assert "authorization" not in request.headers
    assert result.response is not None
    assert result.response.sort_mode == "asc"
    assert result.rows[0][numeric_field] == Decimal("12345678901234.56")
    assert result.rows[1][numeric_field] is None
    assert result.rows[0]["record_date"] == date(2025, 3, 31)
    assert result.rows[0]["src_line_nbr"] == 7
    assert result.saved_states == [FiscalDataResumeConfig(page=2, lower_bound=expected_filter)]
    # The cursor stays in storage until the pipeline calls `on_complete`.
    assert result.final_state == FiscalDataResumeConfig(page=2, lower_bound=expected_filter)
    assert result.completed_state is None


@pytest.mark.parametrize("lower_bound", [None, "2025-01-01"])
def test_resume_preserves_original_filter_when_watermark_advances(lower_bound: str | None) -> None:
    result = run(
        script=[ScriptedResponse(json={"data": [], "meta": {"total-pages": 3}})],
        watermark="2025-03-31",
        resume_state=FiscalDataResumeConfig(page=3, lower_bound=lower_bound),
    )

    assert result.rows == []
    assert result.params("page[number]") == ["3"]
    assert result.params("filter") == [f"record_date:gte:{lower_bound}" if lower_bound else None]
    assert result.saved_states == []


def test_a_run_with_no_saved_state_starts_from_the_first_page() -> None:
    result = run(script=[ScriptedResponse(json={"data": [], "meta": {"total-pages": 1}})])

    assert result.params("page[number]") == ["1"]


@pytest.mark.parametrize("status", [200, 401, 403, 400, 500])
def test_validation_and_error_mapping(status: int) -> None:
    body = ScriptedResponse(status=status, json={"data": []})
    with scripted_network(always(body)) as network:
        if status in (400, 500):
            with pytest.raises(HTTPError):
                validate_credentials()
        else:
            valid, message = validate_credentials()
            assert valid is (status == 200)
            if status in (401, 403):
                sync = run(script=always(body))
                assert isinstance(sync.raised, HTTPError)
                matches = [
                    text
                    for pattern, text in UsTreasuryFiscalDataSource().get_non_retryable_errors().items()
                    if pattern in str(sync.raised)
                ]
                assert matches == [message]
                assert message is not None and "needs no key" in message
            else:
                assert message is None
    request = network.requests_log[0]
    assert request.param("page[size]") == "1"
    assert "authorization" not in request.headers
    if status != 500:
        assert len(network.requests_log) == 1


@pytest.mark.parametrize("field", [None, "record_date", "unknown"])
def test_rejects_wrong_exchange_rate_cursor(field: str | None) -> None:
    result = SourceDriver(UsTreasuryFiscalDataSource(), UsTreasuryFiscalDataSourceConfig()).run(
        "rates_of_exchange",
        [],
        should_use_incremental_field=True,
        incremental_field=field,
        incremental_field_type=IncrementalFieldType.Date,
    )

    assert isinstance(result.raised, ValueError)
    assert "Select effective_date" in str(result.raised)


def test_rejects_unknown_table_without_a_request() -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials("unknown")
        assert not valid
        assert message is not None and "Unknown" in message
        result = run("unknown")

    assert isinstance(result.raised, ValueError)
    assert "Unknown" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []
