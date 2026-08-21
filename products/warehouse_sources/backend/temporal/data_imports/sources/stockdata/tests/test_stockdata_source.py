from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.source import StockDataSource

_INCREMENTAL = {"news": "published_at", "eod": "date", "intraday": "date"}
_FULL_REFRESH_ONLY = {"quote", "dividends", "splits"}


def _make_config(api_token: str = "token", symbols: str | None = "AAPL") -> Any:
    config = MagicMock()
    config.api_token = api_token
    config.symbols = symbols
    return config


class TestStockDataSource:
    def test_get_schemas_marks_incremental_endpoints(self) -> None:
        schemas = {s.name: s for s in StockDataSource().get_schemas(_make_config(), team_id=1)}
        for name, field in _INCREMENTAL.items():
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == [field]
        for name in _FULL_REFRESH_ONLY:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    @parameterized.expand(
        [
            ("http_unauthorized", "401 Client Error: Unauthorized for url: https://api.stockdata.org"),
            ("http_payment_required", "402 Client Error: Payment Required for url: https://api.stockdata.org"),
            ("http_forbidden", "403 Client Error: Forbidden for url: https://api.stockdata.org"),
            ("missing_symbols", "StockData.org API error [missing_symbols]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = StockDataSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
