from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.source import StockDataSource


def _make_config(api_token: str = "token", symbols: str | None = "AAPL") -> Any:
    config = MagicMock()
    config.api_token = api_token
    config.symbols = symbols
    return config


class TestStockDataSource:
    def test_get_schemas_filters_by_names(self) -> None:
        schemas = StockDataSource().get_schemas(_make_config(), team_id=1, names=["news", "eod"])
        assert {s.name for s in schemas} == {"news", "eod"}

    def test_source_for_pipeline_plumbs_symbols_and_keys(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "eod"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2021-04-09"

        response = StockDataSource().source_for_pipeline(_make_config("abc", "AAPL,MSFT"), MagicMock(), inputs)

        assert response.name == "eod"
        assert response.primary_keys == ["ticker", "date"]

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "quote"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.source.stockdata_source"
        ) as mocked:
            StockDataSource().source_for_pipeline(_make_config(), MagicMock(), inputs)
        # A full-refresh run must never forward a stale watermark to the transport.
        assert mocked.call_args.kwargs["db_incremental_field_last_value"] is None

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
