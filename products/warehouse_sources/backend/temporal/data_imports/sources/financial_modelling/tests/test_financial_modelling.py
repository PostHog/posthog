from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling import financial_modelling
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.financial_modelling import (
    FinancialModellingError,
    FinancialModellingResumeConfig,
    _build_url,
    _extract_rows,
    _fetch_page,
    _to_date,
    _window_params,
    financial_modelling_source,
    get_rows,
    parse_symbols,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.settings import (
    FINANCIAL_MODELLING_ENDPOINTS,
)


class TestParseSymbols:
    @parameterized.expand(
        [
            ("comma", "AAPL,MSFT,GOOGL", ["AAPL", "MSFT", "GOOGL"]),
            ("comma_space", "AAPL, MSFT, GOOGL", ["AAPL", "MSFT", "GOOGL"]),
            ("lowercase_uppercased", "aapl,msft", ["AAPL", "MSFT"]),
            ("newline_and_space", "AAPL\nMSFT GOOGL", ["AAPL", "MSFT", "GOOGL"]),
            ("dedupes_preserving_order", "AAPL,MSFT,AAPL", ["AAPL", "MSFT"]),
            ("strips_whitespace", "  AAPL  ,  MSFT ", ["AAPL", "MSFT"]),
            ("empty", "", []),
            ("none", None, []),
        ]
    )
    def test_parse_symbols(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_symbols(raw) == expected


class TestBuildUrl:
    def test_appends_apikey_and_params(self) -> None:
        url = _build_url("profile", {"symbol": "AAPL"}, "secret_key")
        assert url.startswith("https://financialmodelingprep.com/stable/profile?")
        assert "symbol=AAPL" in url
        assert "apikey=secret_key" in url

    def test_url_encodes_param_values(self) -> None:
        url = _build_url("earnings-calendar", {"from": "2024-01-01", "to": "2024-12-31"}, "k")
        assert "from=2024-01-01" in url
        assert "to=2024-12-31" in url


class TestFetchPage:
    def test_client_error_does_not_leak_api_key(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.reason = "Unauthorized"

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page(session, "profile", {"symbol": "AAPL"}, "super_secret_key", MagicMock())

        message = str(exc_info.value)
        assert "super_secret_key" not in message
        # Still carries the stable text get_non_retryable_errors matches on.
        assert message.startswith("401 Client Error: Unauthorized for url: https://financialmodelingprep.com")


class TestExtractRows:
    def test_bare_array_returned_as_is(self) -> None:
        assert _extract_rows([{"a": 1}, {"a": 2}], None) == [{"a": 1}, {"a": 2}]

    def test_wrapped_array_read_from_response_key(self) -> None:
        data = {"symbol": "AAPL", "historical": [{"date": "2024-01-01"}]}
        assert _extract_rows(data, "historical") == [{"date": "2024-01-01"}]

    def test_single_object_is_wrapped(self) -> None:
        assert _extract_rows({"symbol": "AAPL", "price": 1}, None) == [{"symbol": "AAPL", "price": 1}]

    def test_error_body_raises(self) -> None:
        with pytest.raises(FinancialModellingError):
            _extract_rows({"Error Message": "Invalid API KEY"}, None)

    def test_error_body_message_is_non_retryable_matchable(self) -> None:
        # The raised message must carry the stable prefix get_non_retryable_errors keys on, otherwise
        # plan-restriction bodies loop forever instead of disabling the schema.
        with pytest.raises(FinancialModellingError) as exc_info:
            _extract_rows({"Error Message": "Exclusive Endpoint"}, None)
        assert str(exc_info.value).startswith("Financial Modeling Prep API returned an error response")

    def test_unexpected_type_returns_empty(self) -> None:
        assert _extract_rows(None, None) == []


class TestToDate:
    @parameterized.expand(
        [
            ("datetime", datetime(2024, 5, 1, 10, 30, tzinfo=UTC), date(2024, 5, 1)),
            ("date", date(2024, 5, 1), date(2024, 5, 1)),
            ("iso_string", "2024-05-01", date(2024, 5, 1)),
            ("z_string", "2024-05-01T00:00:00Z", date(2024, 5, 1)),
            ("bad_string", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_to_date(self, _name: str, value: Any, expected: date | None) -> None:
        assert _to_date(value) == expected


@freeze_time("2024-06-15")
class TestWindowParams:
    def test_non_windowed_endpoint_returns_empty(self) -> None:
        config = FINANCIAL_MODELLING_ENDPOINTS["company_profiles"]
        assert (
            _window_params(config, should_use_incremental_field=True, db_incremental_field_last_value="2024-01-01")
            == {}
        )

    def test_incremental_uses_last_value_as_from(self) -> None:
        config = FINANCIAL_MODELLING_ENDPOINTS["historical_prices"]
        params = _window_params(config, should_use_incremental_field=True, db_incremental_field_last_value="2024-05-01")
        assert params == {"from": "2024-05-01", "to": "2024-06-15"}

    def test_future_cursor_is_clamped_to_today(self) -> None:
        config = FINANCIAL_MODELLING_ENDPOINTS["historical_prices"]
        params = _window_params(config, should_use_incremental_field=True, db_incremental_field_last_value="2030-01-01")
        assert params == {"from": "2024-06-15", "to": "2024-06-15"}

    def test_first_sync_falls_back_to_lookback(self) -> None:
        config = FINANCIAL_MODELLING_ENDPOINTS["earnings_calendar"]
        params = _window_params(config, should_use_incremental_field=True, db_incremental_field_last_value=None)
        # default_lookback_days = 365 * 2 -> two years before the frozen "today"
        assert params["to"] == "2024-06-15"
        assert params["from"] == "2022-06-16"


class _FakeResumableManager:
    def __init__(self, state: FinancialModellingResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FinancialModellingResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FinancialModellingResumeConfig | None:
        return self._state

    def save_state(self, data: FinancialModellingResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    endpoint: str, symbols: list[str], manager: _FakeResumableManager, monkeypatch: Any, by_symbol: dict[str, Any]
) -> list[dict]:
    def fake_fetch(session: Any, path: str, params: dict[str, Any], api_key: str, logger: Any) -> Any:
        key = params.get("symbol", path)
        return by_symbol[key]

    monkeypatch.setattr(financial_modelling, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="k",
        endpoint=endpoint,
        symbols=symbols,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


class TestGetRowsFanOut:
    def test_fans_out_over_each_symbol_and_injects_symbol(self, monkeypatch: Any) -> None:
        by_symbol = {
            "AAPL": [{"symbol": "AAPL", "companyName": "Apple"}],
            "MSFT": [{"symbol": "MSFT", "companyName": "Microsoft"}],
        }
        rows = _collect("company_profiles", ["AAPL", "MSFT"], _FakeResumableManager(), monkeypatch, by_symbol)
        assert {r["symbol"] for r in rows} == {"AAPL", "MSFT"}

    def test_symbol_injected_when_missing_from_row(self, monkeypatch: Any) -> None:
        # historical_prices rows arrive without a symbol; the fan-out injects it.
        by_symbol = {"AAPL": {"symbol": "AAPL", "historical": [{"date": "2024-01-02", "close": 10}]}}
        rows = _collect("historical_prices", ["AAPL"], _FakeResumableManager(), monkeypatch, by_symbol)
        assert rows == [{"date": "2024-01-02", "close": 10, "symbol": "AAPL"}]

    def test_saves_resume_state_advancing_per_symbol(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        by_symbol = {
            "AAPL": [{"symbol": "AAPL"}],
            "MSFT": [{"symbol": "MSFT"}],
            "GOOGL": [{"symbol": "GOOGL"}],
        }
        _collect("company_profiles", ["AAPL", "MSFT", "GOOGL"], manager, monkeypatch, by_symbol)
        # State is saved after every symbol except the last (no point bookmarking past the end).
        assert [s.symbol_index for s in manager.saved] == [1, 2]

    def test_resumes_from_saved_symbol_index(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(FinancialModellingResumeConfig(symbol_index=1))
        fetched: list[str] = []

        def fake_fetch(session: Any, path: str, params: dict[str, Any], api_key: str, logger: Any) -> Any:
            fetched.append(params["symbol"])
            return [{"symbol": params["symbol"]}]

        monkeypatch.setattr(financial_modelling, "_fetch_page", fake_fetch)
        list(
            get_rows(
                api_key="k",
                endpoint="company_profiles",
                symbols=["AAPL", "MSFT", "GOOGL"],
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )
        # AAPL (index 0) is skipped because the bookmark resumes at index 1.
        assert fetched == ["MSFT", "GOOGL"]


class TestGetRowsMarketWide:
    def test_single_request_no_symbol(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        by_path = {"earnings-calendar": [{"symbol": "AAPL", "date": "2024-01-01"}]}
        rows = _collect("earnings_calendar", [], manager, monkeypatch, by_path)
        assert rows == [{"symbol": "AAPL", "date": "2024-01-01"}]
        # Market-wide endpoints fan out over nothing, so no resume bookmark is saved.
        assert manager.saved == []


class TestFinancialModellingSourceResponse:
    @parameterized.expand(
        [
            ("incremental_uses_desc", "historical_prices", "desc"),
            ("full_refresh_uses_asc", "company_profiles", "asc"),
        ]
    )
    def test_sort_mode(self, _name: str, endpoint: str, expected: str) -> None:
        response = financial_modelling_source(
            api_key="k",
            endpoint=endpoint,
            symbols=["AAPL"],
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected

    @parameterized.expand(
        [
            ("stock_list", ["symbol"]),
            ("income_statements", ["symbol", "date", "period"]),
            ("historical_prices", ["symbol", "date"]),
            ("earnings_calendar", ["symbol", "date"]),
        ]
    )
    def test_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        response = financial_modelling_source(
            api_key="k",
            endpoint=endpoint,
            symbols=["AAPL"],
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.primary_keys == expected_keys

    def test_partitioned_endpoint_has_datetime_partitioning(self) -> None:
        response = financial_modelling_source(
            api_key="k",
            endpoint="historical_prices",
            symbols=["AAPL"],
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]

    def test_unpartitioned_endpoint_has_no_partitioning(self) -> None:
        response = financial_modelling_source(
            api_key="k",
            endpoint="company_profiles",
            symbols=["AAPL"],
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None
