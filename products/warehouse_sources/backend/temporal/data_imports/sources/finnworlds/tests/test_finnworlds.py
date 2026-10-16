from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds import finnworlds
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.finnworlds import (
    FinnworldsAuthError,
    FinnworldsRetryableError,
    _extract_rows,
    _normalize_row,
    _payload_error,
    finnworlds_source,
    get_rows,
    parse_countries,
    parse_tickers,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.settings import (
    FINNWORLDS_ENDPOINTS,
    FinnworldsEndpointConfig,
    ResponseMode,
)


def _logger() -> MagicMock:
    return MagicMock()


def _response(json_body: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_body

    def _raise() -> None:
        if status_code >= 400:
            raise requests.HTTPError(f"{status_code} error", response=resp)

    resp.raise_for_status.side_effect = _raise
    return resp


def _session_returning(*responses: MagicMock) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


class TestParseTickers:
    @parameterized.expand(
        [
            ("comma_separated", "AAPL,MSFT,GOOGL", ["AAPL", "MSFT", "GOOGL"]),
            ("space_separated", "AAPL MSFT", ["AAPL", "MSFT"]),
            ("newline_separated", "AAPL\nMSFT", ["AAPL", "MSFT"]),
            ("mixed_separators", "aapl, msft\n googl", ["AAPL", "MSFT", "GOOGL"]),
            ("lowercase_uppercased", "aapl", ["AAPL"]),
            ("dedupes_preserving_order", "AAPL, MSFT, AAPL", ["AAPL", "MSFT"]),
            ("strips_whitespace", "  AAPL  ", ["AAPL"]),
            ("empty_string", "", []),
            ("none", None, []),
            ("only_separators", " , , ", []),
        ]
    )
    def test_parse_tickers(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_tickers(raw) == expected

    def test_over_max_tickers_is_rejected(self) -> None:
        # Bounds the per-sync outbound fan-out (one request per ticker per table).
        raw = ",".join(f"T{i}" for i in range(finnworlds.MAX_TICKERS + 1))
        with pytest.raises(ValueError, match="Too many tickers"):
            parse_tickers(raw)


class TestParseCountries:
    @parameterized.expand(
        [
            ("comma_separated", "United_States,Germany", ["United_States", "Germany"]),
            ("newline_separated", "United_States\nGermany", ["United_States", "Germany"]),
            ("spaces_become_underscores", "United Kingdom, Germany", ["United_Kingdom", "Germany"]),
            ("keeps_user_spelling", "germany", ["germany"]),
            ("dedupes_case_insensitively", "Germany, germany", ["Germany"]),
            ("strips_whitespace", "  Germany  ", ["Germany"]),
            ("empty_string", "", []),
            ("none", None, []),
            ("only_separators", " , , ", []),
        ]
    )
    def test_parse_countries(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_countries(raw) == expected

    def test_over_max_countries_is_rejected(self) -> None:
        raw = ",".join(f"Country{i}" for i in range(finnworlds.MAX_COUNTRIES + 1))
        with pytest.raises(ValueError, match="Too many countries"):
            parse_countries(raw)


class TestPayloadError:
    @parameterized.expand(
        [
            ("error_key", {"error": "Invalid key"}, "Invalid key"),
            ("error_key_403", {"error": "403 Forbidden"}, "403 Forbidden"),
            ("status_non_200", {"status": {"code": 401, "message": "Unauthorized"}}, "Unauthorized"),
            ("ok_status", {"status": {"code": 200, "message": "OK"}, "result": {}}, None),
            ("no_error", {"result": {"output": []}}, None),
            ("blank_error_ignored", {"error": "  "}, None),
        ]
    )
    def test_payload_error(self, _name: str, payload: dict, expected: str | None) -> None:
        assert _payload_error(payload) == expected


class TestExtractRows:
    def test_result_key(self) -> None:
        payload = {"result": {"analysts": [{"analyst_name": "Jane"}]}}
        rows = _extract_rows(payload, FINNWORLDS_ENDPOINTS["company_ratings"])
        assert rows == [{"analyst_name": "Jane"}]

    def test_top_level(self) -> None:
        payload = {"sec_filings": [{"url": "https://sec.gov/x"}]}
        rows = _extract_rows(payload, FINNWORLDS_ENDPOINTS["sec_filings"])
        assert rows == [{"url": "https://sec.gov/x"}]

    @parameterized.expand(
        [
            ("missing_result", {}),
            ("output_wrong_shape", {"result": {"output": "not-a-list"}}),
            ("non_dict_rows_filtered", {"result": {"output": {"income_statement": ["str", {"date": "x"}]}}}),
        ]
    )
    def test_malformed_responses_degrade_gracefully(self, _name: str, payload: dict) -> None:
        # Shapes are doc-derived, not curl-verified, so the extractor must never raise on a surprise.
        rows = _extract_rows(payload, FINNWORLDS_ENDPOINTS["income_statements"])
        assert all(isinstance(r, dict) for r in rows)


class TestNormalizeRow:
    def test_injects_ticker(self) -> None:
        row = _normalize_row({"date": "2025-03-31"}, FINNWORLDS_ENDPOINTS["dividends"], "AAPL", None)
        assert row["ticker"] == "AAPL"

    def test_injects_period(self) -> None:
        row = _normalize_row({"date": "2025-03-31"}, FINNWORLDS_ENDPOINTS["income_statements"], "AAPL", "quarterly")
        assert row["ticker"] == "AAPL"
        assert row["period"] == "quarterly"

    def test_flattens_nested_rating(self) -> None:
        raw = {"analyst_name": "Jane", "rating": {"date_rating": "2025-01-01", "price_target": "200"}}
        row = _normalize_row(raw, FINNWORLDS_ENDPOINTS["company_ratings"], "AAPL", None)
        assert row["date_rating"] == "2025-01-01"
        assert row["price_target"] == "200"
        assert row["ticker"] == "AAPL"
        assert "rating" not in row

    def test_no_ticker_injection_for_bonds(self) -> None:
        row = _normalize_row({"country": "US"}, FINNWORLDS_ENDPOINTS["bond_yields"], None, None)
        assert "ticker" not in row


class TestGetRows:
    def test_ticker_fanout_yields_per_ticker_with_ticker_injected(self) -> None:
        responses = [
            _response({"result": {"output": {"dividends": [{"date": "2025-01-01", "dividend_rate": "0.5"}]}}}),
            _response({"result": {"output": {"dividends": [{"date": "2025-02-01", "dividend_rate": "0.6"}]}}}),
        ]
        session = _session_returning(*responses)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            batches = list(get_rows("key", "dividends", ["AAPL", "MSFT"], [], _logger()))

        assert len(batches) == 2
        assert batches[0][0]["ticker"] == "AAPL"
        assert batches[1][0]["ticker"] == "MSFT"

    def test_non_ticker_endpoint_single_fetch(self) -> None:
        session = _session_returning(_response({"result": {"output": [{"country": "US", "type": "10Y"}]}}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            batches = list(get_rows("key", "bond_yields", ["AAPL"], [], _logger()))

        assert session.get.call_count == 1
        assert batches == [[{"country": "US", "type": "10Y"}]]

    def test_auth_error_in_body_raises(self) -> None:
        session = _session_returning(_response({"error": "Invalid key"}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            with pytest.raises(FinnworldsAuthError):
                list(get_rows("bad", "dividends", ["AAPL"], [], _logger()))

    def test_non_auth_error_skips_ticker(self) -> None:
        # First ticker has no data (non-auth error), second succeeds — the sync continues.
        responses = [
            _response({"error": "No data found"}),
            _response({"result": {"output": {"dividends": [{"date": "2025-02-01"}]}}}),
        ]
        session = _session_returning(*responses)
        logger = _logger()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            batches = list(get_rows("key", "dividends", ["AAPL", "MSFT"], [], logger))

        assert len(batches) == 1
        assert batches[0][0]["ticker"] == "MSFT"
        logger.warning.assert_called()


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        with pytest.MonkeyPatch.context() as mp:
            # Don't actually sleep between the bounded retries — keep the test fast.
            mp.setattr(finnworlds._fetch.retry, "sleep", lambda *_: None)  # type: ignore[attr-defined]
            with pytest.raises(FinnworldsRetryableError):
                finnworlds._fetch(session, "https://api.finnworlds.com/api/v1/bonds?key=k", _logger())
        # Exhausts the bounded attempts rather than giving up after one try.
        assert session.get.call_count == 5

    def test_http_error_redacts_api_key(self) -> None:
        # A 4xx raises through raise_for_status, whose message embeds the request URL (with ?key=...).
        # The key must never reach the re-raised error that lands in job logs / stored errors.
        resp = MagicMock()
        resp.status_code = 401
        resp.ok = False
        resp.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized for url: "
            "https://api.finnworlds.com/api/v1/information?key=SUPERSECRETKEY&ticker=AAPL",
            response=resp,
        )
        session = MagicMock()
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError) as exc_info:
            finnworlds._fetch(session, "https://api.finnworlds.com/api/v1/information?key=SUPERSECRETKEY", _logger())

        message = str(exc_info.value)
        assert "SUPERSECRETKEY" not in message
        assert "key=REDACTED" in message
        # The host prefix is preserved so get_non_retryable_errors() matching still works.
        assert "api.finnworlds.com" in message


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        session = _session_returning(_response({"result": {"output": {"name": "Apple"}}}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            assert validate_credentials("good") == (True, None)

    def test_invalid_key_body(self) -> None:
        session = _session_returning(_response({"error": "Invalid key"}))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            valid, message = validate_credentials("bad")
        assert valid is False
        assert message == "Invalid Finnworlds API key"

    def test_network_error_reports_distinctly_from_bad_key(self) -> None:
        # A transient connection failure during setup must not be reported as an invalid key.
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            valid, message = validate_credentials("any")
        assert valid is False
        assert message is not None
        assert "Invalid" not in message
        assert "reach the Finnworlds API" in message


class TestFinnworldsSource:
    @parameterized.expand([(name,) for name in FINNWORLDS_ENDPOINTS])
    def test_source_response_primary_keys_and_partitioning(self, endpoint: str) -> None:
        config: FinnworldsEndpointConfig = FINNWORLDS_ENDPOINTS[endpoint]
        response = finnworlds_source("key", endpoint, ["AAPL"], ["United_States"], _logger())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_keys_are_stable_date_fields(self) -> None:
        # Guard against picking an update-style field that rewrites partitions every sync.
        for config in FINNWORLDS_ENDPOINTS.values():
            if config.partition_key:
                assert "updated" not in config.partition_key
                assert "last" not in config.partition_key

    def test_fundamentals_primary_key_includes_ticker_and_period(self) -> None:
        # The id is not globally unique — fan-out aggregates many tickers, so the key must disambiguate.
        for name in ("income_statements", "balance_sheets", "cash_flows"):
            assert FINNWORLDS_ENDPOINTS[name].primary_keys == ["ticker", "period", "date"]

    def test_all_response_modes_are_covered_by_an_endpoint(self) -> None:
        used = {c.response_mode for c in FINNWORLDS_ENDPOINTS.values()}
        assert used == set(ResponseMode)


def _insider_payload(**overrides: Any) -> dict[str, Any]:
    filing: dict[str, Any] = {
        "period_of_report": "2025-08-21",
        "reporting_owner": [
            {
                "owner_id": {"owner_cik": "1000001", "name": "Doe Jane"},
                "owner_role": {
                    "is_director": 0,
                    "is_officer": 1,
                    "is_ten_percent_owner": 0,
                    "is_other": 0,
                    "insider": "Senior Vice President",
                },
            }
        ],
        "non_derivative_table": [
            {
                "security": "Common Stock",
                "activity_date": "2025-08-21",
                "transaction": {"code": "M", "equity_swap": "0"},
                "transaction_amounts": {"shares": "8760", "share_per_price": "0", "acquired_disposed_code": "A"},
                "post_transaction": {"holding": "55790"},
                "ownership_nature": {"direct_or_indirect": "D", "ownership": ""},
            },
            {
                "security": "Common Stock",
                "activity_date": "2025-08-21",
                "transaction": {"code": "M", "equity_swap": "0"},
                "transaction_amounts": {"shares": "3940", "share_per_price": "0", "acquired_disposed_code": "A"},
                "post_transaction": {"holding": "59730"},
                "ownership_nature": {"direct_or_indirect": "D", "ownership": ""},
            },
        ],
        "derivative_table": [
            {
                "derivatives": {
                    "security": "Restricted Stock Unit Award",
                    "activity_date": "2025-08-21",
                    "transaction": {"code": "M", "equity_swap": "0"},
                    "transaction_amounts": {"shares": "8760", "acquired_disposed_code": "D"},
                    "post_transaction": {"shares_owned": "17540"},
                }
            }
        ],
        "footnotes": [{"id": "F1", "text": "Rule 10b5-1 trading plan."}],
    }
    filing.update(overrides)
    return {"status": {"code": 200, "message": "OK"}, "result": filing}


class TestInsiderTransactions:
    def test_a_date_range_returning_several_filings(self) -> None:
        # A single filing comes back as an object; a range can come back as a list of them.
        payload = {"result": [_insider_payload()["result"], _insider_payload(period_of_report="2025-09-02")["result"]]}
        rows = _extract_rows(payload, FINNWORLDS_ENDPOINTS["insider_transactions"])

        assert len(rows) == 6
        assert {r["period_of_report"] for r in rows} == {"2025-08-21", "2025-09-02"}

    @parameterized.expand(
        [
            ("missing_result", {}),
            ("result_is_a_string", {"result": "nope"}),
            ("tables_wrong_shape", {"result": {"non_derivative_table": "nope", "derivative_table": None}}),
            ("entries_not_objects", {"result": {"non_derivative_table": ["nope"]}}),
        ]
    )
    def test_malformed_filings_degrade_gracefully(self, _name: str, payload: dict) -> None:
        assert _extract_rows(payload, FINNWORLDS_ENDPOINTS["insider_transactions"]) == []


class TestCompanyIdentifiers:
    def test_emits_one_row_keeping_the_previous_names(self) -> None:
        payload = {
            "result": {
                "basics": {"ticker": "AAPL"},
                "output": {
                    "name": "Apple Inc.",
                    "cik": "320193",
                    "isin": "US0378331005",
                    "previous_names": [{"name": "APPLE COMPUTER INC", "from": "1994-01-26"}],
                },
            }
        }
        config = FINNWORLDS_ENDPOINTS["company_identifiers"]
        rows = [_normalize_row(row, config, "AAPL", None) for row in _extract_rows(payload, config)]

        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["cik"] == "320193"
        assert rows[0]["previous_names"] == [{"name": "APPLE COMPUTER INC", "from": "1994-01-26"}]


class TestCountryFanout:
    def test_macro_requests_one_country_per_call_and_injects_it(self) -> None:
        responses = [
            _response({"result": {"output": [{"report_name": "Business Confidence", "actual": "-33"}]}}),
            _response({"result": {"output": [{"report_name": "Business Confidence", "actual": "12"}]}}),
        ]
        session = _session_returning(*responses)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            batches = list(
                get_rows("key", "macroeconomic_indicators", ["AAPL"], ["United_Kingdom", "Germany"], _logger())
            )

        requested = [call.args[0] for call in session.get.call_args_list]
        assert "country=United_Kingdom" in requested[0]
        assert "ticker=" not in requested[0]
        assert [batch[0]["country"] for batch in batches] == ["United_Kingdom", "Germany"]

    def test_no_countries_configured_makes_no_requests(self) -> None:
        session = _session_returning()
        logger = _logger()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(finnworlds, "make_tracked_session", lambda **_: session)
            batches = list(get_rows("key", "macroeconomic_indicators", ["AAPL"], [], logger))

        assert batches == []
        session.get.assert_not_called()
        logger.warning.assert_called()
