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
