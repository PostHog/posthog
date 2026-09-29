from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.source import FinnhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finnhub import (
    FinnhubSourceConfig,
)


def _config(**overrides: Any) -> FinnhubSourceConfig:
    base: dict[str, Any] = {"api_key": "key", "symbols": "AAPL", "exchange": "US"}
    base.update(overrides)
    return FinnhubSourceConfig.from_dict(base)


class TestSourceConfig:
    def test_fields(self) -> None:
        fields = {f.name: f for f in FinnhubSource().get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "symbols", "exchange"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        # The fan-out and exchange fields must be optional so market-wide tables work alone.
        assert fields["symbols"].required is False
        assert fields["exchange"].required is False


class TestGetSchemas:
    def test_lists_all_endpoints(self) -> None:
        schemas = FinnhubSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == {
            "stock_symbols",
            "market_news",
            "ipo_calendar",
            "earnings_calendar",
            "country",
            "company_profile",
            "quote",
            "company_news",
            "basic_financials",
            "recommendation_trends",
            "earnings_surprises",
            "financials_reported",
            "stock_candles",
            "sec_filings",
            "insider_transactions",
        }

    def test_incremental_endpoints_advertise_their_cursor(self) -> None:
        # Only endpoints Finnhub lets us filter server-side may advertise incremental sync.
        schemas = {s.name: s for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        incremental = {name: s.incremental_fields[0]["field"] for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {
            "company_news": "datetime",
            "financials_reported": "endDate",
            "stock_candles": "t",
            "sec_filings": "filedDate",
            "insider_transactions": "transactionDate",
        }

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
        ]
    )
    def test_should_sync_default(self, endpoint: str, expected_default: bool) -> None:
        # Per-symbol tables default off — they return nothing until the user lists tickers.
        schemas = {s.name: s for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is expected_default

    def test_names_filter(self) -> None:
        schemas = FinnhubSource().get_schemas(_config(), team_id=1, names=["quote", "country"])
        assert {s.name for s in schemas} == {"quote", "country"}


class TestCanonicalDescriptions:
    def test_descriptions_keyed_by_endpoint_name(self) -> None:
        descriptions = FinnhubSource().get_canonical_descriptions()
        schema_names = {s.name for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        # Every documented key must be a real endpoint name so descriptions actually attach.
        assert set(descriptions).issubset(schema_names)
        assert "company_news" in descriptions


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        assert FinnhubSource.lists_tables_without_credentials is True
        tables = FinnhubSource().get_documented_tables()
        assert len(tables) == 15


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
