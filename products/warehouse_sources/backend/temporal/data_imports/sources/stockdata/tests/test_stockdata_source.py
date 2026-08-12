from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.source import StockDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.stockdata import StockDataResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL = {"news": "published_at", "eod": "date", "intraday": "date"}
_FULL_REFRESH_ONLY = {"quote", "dividends", "splits"}


def _make_config(api_token: str = "token", symbols: str | None = "AAPL") -> Any:
    config = MagicMock()
    config.api_token = api_token
    config.symbols = symbols
    return config


class TestStockDataSource:
    def test_source_type(self) -> None:
        assert StockDataSource().source_type == ExternalDataSourceType.STOCKDATA

    def test_source_config_fields(self) -> None:
        config = StockDataSource().get_source_config
        assert [f.name for f in config.fields] == ["api_token", "symbols"]

        api_token_field = config.fields[0]
        assert isinstance(api_token_field, SourceFieldInputConfig)
        # The API token is a secret credential, so it must render as a password input.
        assert api_token_field.type == "password"
        assert api_token_field.secret is True
        assert api_token_field.required is True

        symbols_field = config.fields[1]
        assert isinstance(symbols_field, SourceFieldInputConfig)
        # Symbols are only needed for the price tables (news works without), so the field is optional.
        assert symbols_field.required is False
        assert symbols_field.secret is False

    def test_source_config_is_released_as_alpha(self) -> None:
        config = StockDataSource().get_source_config
        # The source must be visible to users: unreleasedSource hides the connector entirely, and
        # newness is expressed with the alpha release status instead.
        assert not config.unreleasedSource
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/stockdata"

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = StockDataSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

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

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = StockDataSource().get_schemas(_make_config(), team_id=1, names=["news", "eod"])
        assert {s.name for s in schemas} == {"news", "eod"}

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Invalid StockData.org API token")),
        ]
    )
    def test_validate_credentials_passes_probe_result_through(
        self, _name: str, probe_result: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.source.validate_stockdata_credentials",
            return_value=probe_result,
        ):
            assert StockDataSource().validate_credentials(_make_config(), team_id=1) == probe_result

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = StockDataSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is StockDataResumeConfig

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

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = StockDataSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "news" in descriptions
        assert "eod" in descriptions
