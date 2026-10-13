import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.source import (
    UsTreasuryFiscalDataSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.us_treasury_fiscal_data import (
    FiscalDataResumeConfig,
    fiscal_data_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def make_inputs(
    name: str = "debt_to_penny", incremental: bool = True, watermark: date | str | None = None
) -> SourceInputs:
    return SourceInputs(
        schema_name=name,
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="effective_date" if name == "rates_of_exchange" else "record_date",
        incremental_field_type=IncrementalFieldType.Date,
        job_id="job-test",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def make_manager(saved: FiscalDataResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = saved is not None
    manager.load_state.return_value = saved
    return manager


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {401: "Unauthorized", 403: "Forbidden", 400: "Bad Request", 500: "Server Error"}.get(status, "OK")
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


def collect_rows(output: SourceResponse) -> list[dict[str, Any]]:
    pages = cast(Iterable[Iterable[dict[str, Any]]], output.items())
    return [row for page in pages for row in page]


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
    manager = make_manager()
    sent: list[PreparedRequest] = []
    rows = [
        {
            "record_date": "2025-03-31",
            "effective_date": "2025-04-15",
            "src_line_nbr": "7",
            numeric_field: "12345678901234.56",
        },
        {"record_date": "2025-06-30", "effective_date": "2025-06-30", "src_line_nbr": "8", numeric_field: "null"},
    ]

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        sent.append(request)
        result = response({"data": [rows[len(sent) - 1]], "meta": {"total-pages": 2}})
        result.request = request
        assert request.url is not None
        result.url = request.url
        return result

    with patch("requests.sessions.Session.send", side_effect=send):
        output = fiscal_data_source(make_inputs(name, incremental, watermark), manager)
        actual = collect_rows(output)

    assert len(sent) == 2
    for page, request in enumerate(sent, 1):
        assert request.url is not None
        parsed = urlparse(request.url)
        assert parsed.path == "/services/api/fiscal_service/" + path
        params = parse_qs(parsed.query)
        assert params["page[number]"] == [str(page)]
        assert params["page[size]"] == ["1000"]
        assert params["sort"][0].split(",")[0] == cursor
        assert params.get("filter") == ([f"{cursor}:gte:{expected_filter}"] if expected_filter else None)
        assert "Authorization" not in request.headers
    assert output.sort_mode == "asc"
    assert actual[0][numeric_field] == Decimal("12345678901234.56")
    assert actual[1][numeric_field] is None
    assert actual[0]["record_date"] == date(2025, 3, 31)
    assert actual[0]["src_line_nbr"] == 7
    manager.save_state.assert_called_once_with(FiscalDataResumeConfig(page=2, lower_bound=expected_filter))
    manager.clear_state.assert_not_called()
    assert output.on_complete is not None
    output.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize("lower_bound", [None, "2025-01-01"])
def test_resume_preserves_original_filter_when_watermark_advances(lower_bound: str | None) -> None:
    manager = make_manager(FiscalDataResumeConfig(page=3, lower_bound=lower_bound))
    with patch(
        "requests.sessions.Session.send", return_value=response({"data": [], "meta": {"total-pages": 3}})
    ) as send:
        output = fiscal_data_source(make_inputs(watermark="2025-03-31"), manager)
        assert collect_rows(output) == []
    request = send.call_args.args[0]
    params = parse_qs(urlparse(request.url).query)
    assert params["page[number]"] == ["3"]
    assert params.get("filter") == ([f"record_date:gte:{lower_bound}"] if lower_bound else None)
    manager.save_state.assert_not_called()
    assert send.call_count == 1


@pytest.mark.parametrize("status", [200, 401, 403, 400, 500])
def test_validation_and_error_mapping(status: int) -> None:
    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        result = response({"data": []}, status)
        result.request = request
        assert request.url is not None
        result.url = request.url
        return result

    with patch("requests.sessions.Session.send", side_effect=send) as mocked:
        if status in (400, 500):
            with pytest.raises(HTTPError):
                validate_credentials()
        else:
            valid, message = validate_credentials()
            assert valid is (status == 200)
            if status in (401, 403):
                result = send(mocked.call_args.args[0])
                with pytest.raises(HTTPError) as error:
                    result.raise_for_status()
                matches = [
                    text
                    for pattern, text in UsTreasuryFiscalDataSource().get_non_retryable_errors().items()
                    if pattern in str(error.value)
                ]
                assert matches == [message]
                assert message is not None and "needs no key" in message
            else:
                assert message is None
    request = mocked.call_args.args[0]
    assert parse_qs(urlparse(request.url).query)["page[size]"] == ["1"]
    assert "Authorization" not in request.headers
    assert mocked.call_count == 1


@pytest.mark.parametrize("field", [None, "record_date", "unknown"])
def test_rejects_wrong_exchange_rate_cursor(field: str | None) -> None:
    inputs = make_inputs("rates_of_exchange")
    inputs.incremental_field = field
    with pytest.raises(ValueError, match="Select effective_date"):
        fiscal_data_source(inputs, make_manager())


def test_rejects_unknown_table_without_a_request() -> None:
    with patch("requests.sessions.Session.send") as send:
        valid, message = validate_credentials("unknown")
        assert not valid
        assert message is not None and "Unknown" in message
        with pytest.raises(ValueError, match="Unknown"):
            fiscal_data_source(make_inputs("unknown"), make_manager())
    send.assert_not_called()
