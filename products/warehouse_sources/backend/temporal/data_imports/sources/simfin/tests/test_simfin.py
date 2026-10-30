from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.simfin import SimFinSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.simfin import (
    SimFinAPIError,
    _normalize_column_name,
    _parse_common_shares,
    _parse_companies,
    _parse_company_details,
    _parse_prices,
    _parse_statements,
    _parse_weighted_shares,
    parse_tickers,
    validate_credentials,
    validate_tickers,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.source import SimFinSource


def _driver(tickers: str = "AAPL, MSFT") -> SourceDriver:
    return SourceDriver(SimFinSource(), SimFinSourceConfig(api_key="KEY", tickers=tickers))


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
            ScriptedResponse(
                json=[
                    {
                        "id": 1,
                        "ticker": "AAPL",
                        "statements": [{"statement": "PL", "columns": ["Fiscal Year"], "data": [[2024]]}],
                    }
                ]
            ),
            ScriptedResponse(
                json=[
                    {
                        "id": 2,
                        "ticker": "MSFT",
                        "statements": [{"statement": "PL", "columns": ["Fiscal Year"], "data": [[2023]]}],
                    }
                ]
            ),
        ]

        result = _driver().run("income_statements", responses)

        assert result.raised is None
        assert [(r["ticker"], r["fiscal_year"]) for r in result.rows] == [("AAPL", 2024), ("MSFT", 2023)]
        assert [request.origin for request in result.requests] == ["https://backend.simfin.com"] * 2
        assert result.paths == ["/api/v3/companies/statements/compact"] * 2
        assert result.params("ticker") == ["AAPL", "MSFT"]
        # The statement type must ride on every request or the table silently fills with the API default.
        assert result.params("statements") == ["pl"] * 2

    def test_get_rows_companies_is_a_single_request_without_ticker(self) -> None:
        result = _driver().run("companies", [ScriptedResponse(json=[{"id": 1, "ticker": "AAPL"}])])

        assert result.rows == [{"id": 1, "ticker": "AAPL"}]
        assert len(result.requests) == 1
        assert result.params("ticker") == [None]

    def test_get_rows_skips_empty_ticker_but_syncs_the_rest(self) -> None:
        responses = [
            ScriptedResponse(json=[]),
            ScriptedResponse(json=[{"id": 2, "ticker": "MSFT", "columns": ["Date"], "data": [["2024-05-07"]]}]),
        ]
        logger = MagicMock()

        result = _driver("BADTICKER, MSFT").run("share_prices", responses, logger=logger)

        assert [r["ticker"] for r in result.rows] == ["MSFT"]
        logger.warning.assert_called_once()

    def test_get_rows_propagates_http_errors(self) -> None:
        # The raised message must keep the "401 Client Error ... backend.simfin.com" shape that
        # get_non_retryable_errors keys on, so bad credentials fail permanently instead of retrying.
        result = _driver("AAPL").run("share_prices", [ScriptedResponse(status=401, json=[])])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url" in str(result.raised)

    def test_session_carries_auth_header_and_redacts_key(self) -> None:
        config = SimFinSourceConfig(api_key="SECRETKEY", tickers="AAPL")

        result = SourceDriver(SimFinSource(), config).run("companies", [ScriptedResponse(json=[])])

        assert result.session_options[0]["headers"]["Authorization"] == "api-key SECRETKEY"
        assert result.session_options[0]["redact_values"] == ("SECRETKEY",)
        assert result.requests[0].headers["authorization"] == "api-key SECRETKEY"

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
        response = _driver("AAPL").run(endpoint, always(ScriptedResponse(json=[]))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_validate_credentials_empty_key_skips_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("   ", "v3") is False

        assert network.requests_log == []
        assert network.session_options == []
