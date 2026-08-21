import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source import CoinGeckoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coingecko import (
    CoinGeckoSourceConfig,
)


class TestCoinGeckoSource:
    def setup_method(self) -> None:
        self.source = CoinGeckoSource()
        self.team_id = 123
        self.config = CoinGeckoSourceConfig(api_key="CG-test", plan="demo")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your CoinGecko API key. Check that the key is correct and that CoinGecko is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.source.validate_coingecko_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("demo", "CG-test")
