from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.source import FinnhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FinnhubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(**overrides: Any) -> FinnhubSourceConfig:
    base: dict[str, Any] = {"api_key": "key", "symbols": "AAPL", "exchange": "US"}
    base.update(overrides)
    return FinnhubSourceConfig.from_dict(base)


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert FinnhubSource().source_type == ExternalDataSourceType.FINNHUB

    def test_source_config_basics(self) -> None:
        config = FinnhubSource().get_source_config
        assert config.label == "Finnhub"
        assert config.category == DataWarehouseSourceCategory.FINANCE___ACCOUNTING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/finnhub"

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
        }

    def test_only_company_news_is_incremental(self) -> None:
        schemas = {s.name: s for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"company_news"}
        assert schemas["company_news"].incremental_fields[0]["field"] == "datetime"

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
        ]
    )
    def test_should_sync_default(self, endpoint: str, expected_default: bool) -> None:
        # Per-symbol tables default off — they return nothing until the user lists tickers.
        schemas = {s.name: s for s in FinnhubSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].should_sync_default is expected_default

    def test_names_filter(self) -> None:
        schemas = FinnhubSource().get_schemas(_config(), team_id=1, names=["quote", "country"])
        assert {s.name for s in schemas} == {"quote", "country"}


class TestValidateCredentials:
    def test_delegates_to_transport(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_validate(api_key: str, schema_name: str | None = None) -> tuple[bool, str | None]:
            captured["api_key"] = api_key
            captured["schema_name"] = schema_name
            return True, None

        monkeypatch.setattr(source_module, "validate_finnhub_credentials", fake_validate)
        valid, msg = FinnhubSource().validate_credentials(_config(), team_id=1, schema_name="quote")
        assert (valid, msg) == (True, None)
        assert captured == {"api_key": "key", "schema_name": "quote"}


class TestNonRetryableErrors:
    def test_marks_auth_errors_non_retryable(self) -> None:
        errors = FinnhubSource().get_non_retryable_errors()
        assert any(k.startswith("401 Client Error") for k in errors)
        assert any(k.startswith("403 Client Error") for k in errors)


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
        assert len(tables) == 11


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
