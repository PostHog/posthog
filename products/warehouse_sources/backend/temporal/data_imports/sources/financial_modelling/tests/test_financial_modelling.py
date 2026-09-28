from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling import financial_modelling
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.financial_modelling import (
    FinancialModellingError,
    FinancialModellingResumeConfig,
    _build_url,
    _extract_rows,
    _fetch_page,
    _recent_quarters,
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


class TestWindowParams:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-06-15", tick=False):
            yield

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


class TestRecentQuarters:
    @parameterized.expand(
        [
            # The quarter `today` falls in is still open, so the walk starts at the one before it.
            ("mid_q2", date(2024, 5, 20), [(2024, 1), (2023, 4), (2023, 3)]),
            ("first_day_of_q1_rolls_back_a_year", date(2024, 1, 1), [(2023, 4), (2023, 3), (2023, 2)]),
            ("last_day_of_q4", date(2024, 12, 31), [(2024, 3), (2024, 2), (2024, 1)]),
        ]
    )
    def test_walks_back_from_the_last_completed_quarter(
        self, _name: str, today: date, expected: list[tuple[int, int]]
    ) -> None:
        assert _recent_quarters(3, today) == expected

    def test_spans_multiple_year_boundaries(self) -> None:
        quarters = _recent_quarters(8, date(2024, 5, 20))
        assert quarters[0] == (2024, 1)
        assert quarters[-1] == (2022, 2)
        assert len(set(quarters)) == 8


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
    endpoint: str, symbols: list[str], manager: _FakeResumableManager, by_symbol: dict[str, Any]
) -> list[dict]:
    def fake_fetch(session: Any, path: str, params: dict[str, Any], api_key: str, logger: Any) -> Any:
        key = params.get("symbol", path)
        return by_symbol[key]

    rows: list[dict] = []
    with patch.object(financial_modelling, "_fetch_page", fake_fetch):
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
    def test_fans_out_over_each_symbol_and_injects_symbol(self) -> None:
        by_symbol = {
            "AAPL": [{"symbol": "AAPL", "companyName": "Apple"}],
            "MSFT": [{"symbol": "MSFT", "companyName": "Microsoft"}],
        }
        rows = _collect("company_profiles", ["AAPL", "MSFT"], _FakeResumableManager(), by_symbol)
        assert {r["symbol"] for r in rows} == {"AAPL", "MSFT"}

    def test_symbol_injected_when_missing_from_row(self) -> None:
        # historical_prices rows arrive without a symbol; the fan-out injects it.
        by_symbol = {"AAPL": {"symbol": "AAPL", "historical": [{"date": "2024-01-02", "close": 10}]}}
        rows = _collect("historical_prices", ["AAPL"], _FakeResumableManager(), by_symbol)
        assert rows == [{"date": "2024-01-02", "close": 10, "symbol": "AAPL"}]

    def test_saves_resume_state_advancing_per_symbol(self) -> None:
        manager = _FakeResumableManager()
        by_symbol = {
            "AAPL": [{"symbol": "AAPL"}],
            "MSFT": [{"symbol": "MSFT"}],
            "GOOGL": [{"symbol": "GOOGL"}],
        }
        _collect("company_profiles", ["AAPL", "MSFT", "GOOGL"], manager, by_symbol)
        # State is saved after every symbol except the last (no point bookmarking past the end).
        assert [s.symbol_index for s in manager.saved] == [1, 2]

    def test_resumes_from_saved_symbol_index(self) -> None:
        manager = _FakeResumableManager(FinancialModellingResumeConfig(symbol_index=1))
        fetched: list[str] = []

        def fake_fetch(session: Any, path: str, params: dict[str, Any], api_key: str, logger: Any) -> Any:
            fetched.append(params["symbol"])
            return [{"symbol": params["symbol"]}]

        with patch.object(financial_modelling, "_fetch_page", fake_fetch):
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


class TestGetRowsRequestParams:
    def _params_for(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake_fetch(session: Any, path: str, params: dict[str, Any], api_key: str, logger: Any) -> Any:
            captured.update(params)
            return []

        with patch.object(financial_modelling, "_fetch_page", fake_fetch):
            list(
                get_rows(
                    api_key="k",
                    endpoint=endpoint,
                    symbols=["AAPL"],
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    **kwargs,
                )
            )
        return captured

    @parameterized.expand(
        [
            ("key_metrics",),
            ("ratios",),
            ("dividends",),
            ("earnings",),
            ("splits",),
            ("historical_market_capitalization",),
        ]
    )
    def test_requests_the_maximum_page_size(self, endpoint: str) -> None:
        # These endpoints have no page cursor, so dropping `limit` truncates the symbol's history
        # to FMP's small default instead of failing.
        assert self._params_for(endpoint)["limit"] == "1000"

    @parameterized.expand(
        [
            ("key_metrics",),
            ("ratios",),
            ("dividends",),
            ("earnings",),
            ("key_metrics_ttm",),
            ("splits",),
            ("market_capitalization",),
        ]
    )
    def test_no_date_window_is_sent(self, endpoint: str) -> None:
        # None of these accept `from`/`to`, so a watermark must not leak into the query.
        params = self._params_for(
            endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01",
        )
        assert "from" not in params
        assert "to" not in params

    def test_ttm_endpoint_sends_only_the_symbol(self) -> None:
        assert self._params_for("key_metrics_ttm") == {"symbol": "AAPL"}

    def test_market_cap_history_keeps_the_limit_alongside_the_window(self) -> None:
        # The endpoint's `limit` defaults to 100, so dropping it would truncate the requested window
        # rather than fail.
        params = self._params_for(
            "historical_market_capitalization",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01",
        )
        assert params["from"] == "2024-01-01"
        assert params["limit"] == "1000"

    @parameterized.expand([("company_profiles",), ("splits",), ("market_capitalization",)])
    def test_non_quarterly_endpoints_send_no_period(self, endpoint: str) -> None:
        params = self._params_for(endpoint)
        assert "year" not in params
        assert "quarter" not in params


class TestGetRowsQuarterFanOut:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-06-15", tick=False):
            yield

    def _requests_for(self, endpoint: str, symbols: list[str], manager: Any) -> list[dict[str, Any]]:
        captured: list[dict[str, Any]] = []

        def fake_fetch(session: Any, path: str, params: dict[str, Any], api_key: str, logger: Any) -> Any:
            captured.append(dict(params))
            return []

        with patch.object(financial_modelling, "_fetch_page", fake_fetch):
            list(
                get_rows(
                    api_key="k",
                    endpoint=endpoint,
                    symbols=symbols,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return captured

    def test_requests_every_quarter_for_every_symbol(self) -> None:
        # The endpoint answers for one quarter at a time, so a missing quarter is a silent hole in
        # the series rather than an error.
        requests_made = self._requests_for("institutional_positions_summary", ["AAPL", "MSFT"], _FakeResumableManager())
        quarters = FINANCIAL_MODELLING_ENDPOINTS["institutional_positions_summary"].quarters_lookback
        assert quarters is not None
        assert len(requests_made) == 2 * quarters
        assert {(r["symbol"], r["year"], r["quarter"]) for r in requests_made[:2]} == {
            ("AAPL", "2024", "1"),
            ("AAPL", "2023", "4"),
        }

    def test_bookmark_advances_once_per_symbol_not_per_quarter(self) -> None:
        # Resume state indexes symbols; saving per quarter would skip the rest of a symbol's series
        # after an interruption.
        manager = _FakeResumableManager()
        self._requests_for("institutional_positions_summary", ["AAPL", "MSFT", "GOOGL"], manager)
        assert [state.symbol_index for state in manager.saved] == [1, 2]


class TestGetRowsMarketWide:
    @parameterized.expand(
        [
            ("earnings_calendar", "earnings-calendar", {"symbol": "AAPL", "date": "2024-01-01"}),
            ("available_exchanges", "available-exchanges", {"exchange": "AMEX", "name": "NYSE Arca"}),
            ("available_sectors", "available-sectors", {"sector": "Basic Materials"}),
            ("available_industries", "available-industries", {"industry": "Steel"}),
        ]
    )
    def test_single_request_no_symbol(self, endpoint: str, path: str, row: dict) -> None:
        # These endpoints take no symbol, so the row must not gain one and no bookmark is saved.
        manager = _FakeResumableManager()
        rows = _collect(endpoint, [], manager, {path: [row]})
        assert rows == [row]
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
            ("key_metrics", ["symbol", "date", "period"]),
            ("ratios", ["symbol", "date", "period"]),
            # The TTM endpoints return one always-current row per symbol, with no fiscal date.
            ("key_metrics_ttm", ["symbol"]),
            ("ratios_ttm", ["symbol"]),
            ("dividends", ["symbol", "date"]),
            ("earnings", ["symbol", "date"]),
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

    @parameterized.expand([("company_profiles",), ("key_metrics_ttm",), ("ratios_ttm",)])
    def test_unpartitioned_endpoint_has_no_partitioning(self, endpoint: str) -> None:
        response = financial_modelling_source(
            api_key="k",
            endpoint=endpoint,
            symbols=["AAPL"],
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode is None
        assert response.partition_keys is None
