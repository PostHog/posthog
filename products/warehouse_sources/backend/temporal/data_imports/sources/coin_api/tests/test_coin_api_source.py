import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api import CoinApiResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.source import CoinApiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoinApiSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCoinApiSource:
    def setup_method(self) -> None:
        self.source = CoinApiSource()
        self.team_id = 123
        self.config = CoinApiSourceConfig(api_key="key", symbol_id="BITSTAMP_SPOT_BTC_USD", period_id="1DAY")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.COINAPI

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "CoinApi"
        assert config.label == "CoinAPI"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Shipped behind the unreleased flag until the alpha has been exercised end to end.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/coin-api"
        assert [f.name for f in config.fields] == [
            "api_key",
            "exchange_rate_base_asset",
            "symbol_id",
            "period_id",
            "start_date",
        ]

    def test_api_key_field_is_secret_password(self) -> None:
        key_field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == "api_key"
        )
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://rest.coinapi.io/v1/assets",
            "403 Client Error: Forbidden for url: https://rest.coinapi.io/v1/ohlcv/SYM/history",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://rest.coinapi.io/v1/trades/SYM/history",
            "500 Server Error for url: https://rest.coinapi.io/v1/exchanges",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_schemas_marks_only_timeseries_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        for name in ("assets", "exchanges", "symbols", "exchange_rates"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
        for name in ("ohlcv_history", "trades_history"):
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True

    def test_timeseries_endpoints_off_by_default(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["assets"].should_sync_default is True
        assert schemas["ohlcv_history"].should_sync_default is False
        assert schemas["trades_history"].should_sync_default is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["ohlcv_history"])
        assert [s.name for s in schemas] == ["ohlcv_history"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your CoinAPI key. Check that the key is correct and that CoinAPI is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.source.validate_coin_api_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CoinApiResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.source.coin_api_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "ohlcv_history"
        inputs.should_use_incremental_field = True
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "ohlcv_history"
        assert kwargs["symbol_id"] == "BITSTAMP_SPOT_BTC_USD"
        assert kwargs["period_id"] == "1DAY"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.source.coin_api_source")
    def test_source_for_pipeline_coerces_blank_optionals_to_defaults(self, mock_source: mock.MagicMock) -> None:
        config = CoinApiSourceConfig(api_key="key")
        inputs = mock.MagicMock()
        inputs.schema_name = "exchange_rates"
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["symbol_id"] == ""
        assert kwargs["period_id"] == "1DAY"
        assert kwargs["exchange_rate_base_asset"] == "USD"
        assert kwargs["start_date"] == ""

    def test_canonical_descriptions_cover_key_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert "ohlcv_history" in descriptions
        assert "price_close" in descriptions["ohlcv_history"]["columns"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
