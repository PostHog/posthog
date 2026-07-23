from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.simfin import (
    SimFinAPIError,
    _normalize_column_name,
    _parse_common_shares,
    _parse_companies,
    _parse_company_details,
    _parse_prices,
    _parse_statements,
    _parse_weighted_shares,
    get_rows,
    parse_tickers,
    simfin_source,
    validate_credentials,
    validate_tickers,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.simfin.simfin"


def _response(*, body: Any = None, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body if body is not None else []
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: Unauthorized for url: https://backend.simfin.com/api/v3/companies/list",
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    return response


def _session_returning(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


def _collect_rows(batches: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in batches:
        rows.extend(batch)
    return rows


class TestSimFin:
    @parameterized.expand(
        [
            ("spaces", "Fiscal Year", "fiscal_year"),
            ("multi_word", "Adjusted Closing Price", "adjusted_closing_price"),
            ("punctuation", "Adj. Close", "adj_close"),
            ("already_clean", "date", "date"),
        ]
    )
    def test_normalize_column_name(self, _name: str, raw: str, expected: str) -> None:
        assert _normalize_column_name(raw) == expected

    @parameterized.expand(
        [
            ("dedup_upper_strip", " aapl, MSFT ,, goog, AAPL ", ["AAPL", "MSFT", "GOOG"]),
            ("empty", "", []),
            ("only_commas", " , , ", []),
            ("dotted_class_share", "brk.b", ["BRK.B"]),
        ]
    )
    def test_parse_tickers(self, _name: str, raw: str, expected: list[str]) -> None:
        assert parse_tickers(raw) == expected

    @parameterized.expand(
        [
            ("valid", "AAPL, MSFT", None),
            ("empty", "  ", "Enter at least one ticker (e.g. AAPL, MSFT)"),
            ("over_limit", ",".join(f"T{i}" for i in range(101)), "Too many tickers"),
        ]
    )
    def test_validate_tickers_bounds_the_list(self, _name: str, raw: str, expected_error_fragment: str | None) -> None:
        _, error = validate_tickers(raw)
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error

    def test_parse_statements_reshapes_columns_and_injects_company_fields(self) -> None:
        body = [
            {
                "id": 111052,
                "name": "Apple Inc",
                "ticker": "AAPL",
                "currency": "USD",
                "isin": "US0378331005",
                "statements": [
                    {
                        "statement": "PL",
                        "columns": ["Fiscal Period", "Fiscal Year", "Report Date", "Revenue"],
                        "data": [["Q1", 2024, "2023-12-30", 119575000000], ["FY", 2024, "2024-09-28", 391035000000]],
                    }
                ],
            }
        ]
        rows = list(_parse_statements(body, "AAPL"))
        assert rows == [
            {
                "id": 111052,
                "name": "Apple Inc",
                "ticker": "AAPL",
                "currency": "USD",
                "isin": "US0378331005",
                "fiscal_period": "Q1",
                "fiscal_year": 2024,
                "report_date": "2023-12-30",
                "revenue": 119575000000,
            },
            {
                "id": 111052,
                "name": "Apple Inc",
                "ticker": "AAPL",
                "currency": "USD",
                "isin": "US0378331005",
                "fiscal_period": "FY",
                "fiscal_year": 2024,
                "report_date": "2024-09-28",
                "revenue": 391035000000,
            },
        ]

    def test_parse_statements_skips_companies_without_statements(self) -> None:
        assert list(_parse_statements([{"id": 1, "ticker": "AAPL", "statements": None}], "AAPL")) == []

    def test_parse_prices_reshapes_columns_and_injects_company_fields(self) -> None:
        body = [
            {
                "id": 111052,
                "name": "Apple Inc",
                "ticker": "AAPL",
                "currency": "USD",
                "columns": ["Date", "Adjusted Closing Price", "Trading Volume"],
                "data": [["2024-05-07", 182.4, 45000000]],
            }
        ]
        rows = list(_parse_prices(body, "AAPL"))
        assert rows == [
            {
                "id": 111052,
                "name": "Apple Inc",
                "ticker": "AAPL",
                "currency": "USD",
                "isin": None,
                "date": "2024-05-07",
                "adjusted_closing_price": 182.4,
                "trading_volume": 45000000,
            }
        ]

    def test_parse_companies_yields_objects_as_returned(self) -> None:
        body = [{"id": 111052, "ticker": "AAPL", "name": "Apple Inc", "sectorCode": 101}]
        assert list(_parse_companies(body, None)) == body

    def test_parse_company_details_keeps_camel_case_columns(self) -> None:
        # Column names on this endpoint are already camelCase identifiers matching /companies/list;
        # normalizing them would make the two company tables' column names diverge.
        body = {"columns": ["id", "ticker", "sectorCode", "numEmployees"], "data": [[111052, "AAPL", 101, 164000]]}
        assert list(_parse_company_details(body, "AAPL")) == [
            {"id": 111052, "ticker": "AAPL", "sectorCode": 101, "numEmployees": 164000}
        ]

    def test_parse_common_shares_maps_positional_rows(self) -> None:
        body = [[111052, "2024-05-07", 15334082000]]
        assert list(_parse_common_shares(body, "AAPL")) == [
            {"id": 111052, "date": "2024-05-07", "common_shares_outstanding": 15334082000}
        ]

    def test_parse_weighted_shares_maps_positional_rows(self) -> None:
        body = [[111052, "2024-09-28", 2024, "FY", 15343783000, 15408095000]]
        assert list(_parse_weighted_shares(body, "AAPL")) == [
            {
                "id": 111052,
                "date": "2024-09-28",
                "fiscal_year": 2024,
                "period": "FY",
                "basic_shares_outstanding": 15343783000,
                "diluted_shares_outstanding": 15408095000,
            }
        ]

    @parameterized.expand(
        [
            ("companies_dict", _parse_companies, {"error": "nope"}),
            ("details_list", _parse_company_details, [{"id": 1}]),
            ("statements_dict", _parse_statements, {"columns": []}),
            ("prices_dict", _parse_prices, {"columns": []}),
            ("common_shares_dict", _parse_common_shares, {"data": []}),
            ("weighted_shares_dict", _parse_weighted_shares, {"data": []}),
        ]
    )
    def test_parsers_raise_on_unexpected_shape(self, _name: str, parser: Any, body: Any) -> None:
        # An upstream response-shape change must fail the sync loudly, not silently truncate the table.
        with pytest.raises(SimFinAPIError):
            list(parser(body, "AAPL"))

    def test_get_rows_fans_out_one_request_per_ticker_with_endpoint_params(self) -> None:
        responses = [
            _response(
                body=[
                    {
                        "id": 1,
                        "ticker": "AAPL",
                        "statements": [{"statement": "PL", "columns": ["Fiscal Year"], "data": [[2024]]}],
                    }
                ]
            ),
            _response(
                body=[
                    {
                        "id": 2,
                        "ticker": "MSFT",
                        "statements": [{"statement": "PL", "columns": ["Fiscal Year"], "data": [[2023]]}],
                    }
                ]
            ),
        ]
        session = _session_returning(responses)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("KEY", ["AAPL", "MSFT"], "income_statements", "v3", MagicMock()))

        assert [(r["ticker"], r["fiscal_year"]) for r in rows] == [("AAPL", 2024), ("MSFT", 2023)]
        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls == ["https://backend.simfin.com/api/v3/companies/statements/compact"] * 2
        params = [call.kwargs["params"] for call in session.get.call_args_list]
        assert params[0]["ticker"] == "AAPL"
        assert params[1]["ticker"] == "MSFT"
        # The statement type must ride on every request or the table silently fills with the API default.
        assert all(p["statements"] == "pl" for p in params)

    def test_get_rows_companies_is_a_single_request_without_ticker(self) -> None:
        session = _session_returning([_response(body=[{"id": 1, "ticker": "AAPL"}])])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _collect_rows(get_rows("KEY", ["AAPL", "MSFT"], "companies", "v3", MagicMock()))
        assert rows == [{"id": 1, "ticker": "AAPL"}]
        assert session.get.call_count == 1
        assert "ticker" not in session.get.call_args.kwargs["params"]

    def test_get_rows_skips_empty_ticker_but_syncs_the_rest(self) -> None:
        responses = [
            _response(body=[]),
            _response(body=[{"id": 2, "ticker": "MSFT", "columns": ["Date"], "data": [["2024-05-07"]]}]),
        ]
        logger = MagicMock()
        with patch(f"{MODULE}.make_tracked_session", return_value=_session_returning(responses)):
            rows = _collect_rows(get_rows("KEY", ["BADTICKER", "MSFT"], "share_prices", "v3", logger))
        assert [r["ticker"] for r in rows] == ["MSFT"]
        logger.warning.assert_called_once()

    def test_get_rows_propagates_http_errors(self) -> None:
        # The raised message must keep the "401 Client Error ... backend.simfin.com" shape that
        # get_non_retryable_errors keys on, so bad credentials fail permanently instead of retrying.
        session = _session_returning([_response(status=401)])
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(requests.HTTPError, match="401 Client Error: Unauthorized for url"):
                _collect_rows(get_rows("KEY", ["AAPL"], "share_prices", "v3", MagicMock()))

    def test_session_carries_auth_header_and_redacts_key(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value = _session_returning([_response(body=[])])
            _collect_rows(get_rows("SECRETKEY", [], "companies", "v3", MagicMock()))
        kwargs = make_session.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "api-key SECRETKEY"
        assert kwargs["redact_values"] == ("SECRETKEY",)

    @parameterized.expand(
        [
            ("companies", ["id"], None),
            ("income_statements", ["id", "fiscal_year", "fiscal_period"], "report_date"),
            ("share_prices", ["id", "date"], "date"),
            ("weighted_shares_outstanding", ["id", "date", "fiscal_year", "period"], None),
        ]
    )
    def test_simfin_source_maps_primary_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None
    ) -> None:
        response = simfin_source("KEY", ["AAPL"], endpoint, "v3", MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    @parameterized.expand(
        [
            ("valid", "KEY", 200, True),
            ("unauthorized", "KEY", 401, False),
            ("forbidden", "KEY", 403, False),
        ]
    )
    def test_validate_credentials(self, _name: str, api_key: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(status=status)
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials(api_key, "v3") is expected

    def test_validate_credentials_empty_key_skips_request(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as make_session:
            assert validate_credentials("   ", "v3") is False
        make_session.assert_not_called()

    def test_validate_credentials_network_error_returns_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("KEY", "v3") is False
