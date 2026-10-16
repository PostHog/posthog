import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.source import CoinApiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coinapi import (
    CoinApiSourceConfig,
)


class TestCoinApiSource:
    def setup_method(self) -> None:
        self.source = CoinApiSource()
        self.team_id = 123
        self.config = CoinApiSourceConfig(api_key="key", symbol_id="BITSTAMP_SPOT_BTC_USD", period_id="1DAY")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["ohlcv_history"])
        assert [s.name for s in schemas] == ["ohlcv_history"]

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
        assert kwargs["metric_id"] == ""
        assert kwargs["exchange_rate_base_asset"] == "USD"
        assert kwargs["exchange_rate_quote_asset"] == ""
        assert kwargs["start_date"] == ""
