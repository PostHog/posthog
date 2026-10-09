from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.source import FinnhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finnhub import (
    FinnhubSourceConfig,
)


def _config(**overrides: Any) -> FinnhubSourceConfig:
    base: dict[str, Any] = {"api_key": "key", "symbols": "AAPL", "indices": "^GSPC", "exchange": "US"}
    base.update(overrides)
    return FinnhubSourceConfig.from_dict(base)


class TestGetSchemas:
    @parameterized.expand(
        [
            ("stock_symbols", True),
            ("market_news", True),
            ("ipo_calendar", True),
            ("earnings_calendar", True),
            ("country", True),
            ("company_profile", False),
            ("quote", False),
            ("company_news", False),
            ("basic_financials", False),
            ("recommendation_trends", False),
            ("earnings_surprises", False),
            ("financials_reported", False),
            ("stock_candles", False),
            ("sec_filings", False),
            ("insider_transactions", False),
            ("dividends", False),
            ("peers", False),
            ("index_constituents", False),
            ("economic_calendar", False),
        ]
    )
    def test_should_sync_default(self, endpoint: str, expected_default: bool) -> None:
        # Per-symbol tables default off — they return nothing until the user lists tickers.
        schemas = {s.name: s for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is expected_default

    def test_names_filter(self) -> None:
        schemas = FinnhubSource().get_schemas(_config(), team_id=1, names=["quote", "country"])
        assert {s.name for s in schemas} == {"quote", "country"}


class TestSourceForPipeline:
    def test_plumbs_schema_into_source_response(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "company_news"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        inputs.logger = MagicMock()
        # items is a lazy lambda, so building the response does not touch the network.
        response = FinnhubSource().source_for_pipeline(_config(), inputs)
        assert response.name == "company_news"
        assert response.primary_keys == ["id", "symbol"]


if __name__ == "__main__":
    pytest.main([__file__])
