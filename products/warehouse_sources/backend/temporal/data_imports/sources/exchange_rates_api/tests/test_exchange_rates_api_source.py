import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source import (
    ExchangeRatesApiSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.exchangeratesapi import (
    ExchangeRatesApiSourceConfig,
)


class TestExchangeRatesApiSource:
    def setup_method(self) -> None:
        self.source = ExchangeRatesApiSource()
        self.team_id = 123
        self.config = ExchangeRatesApiSourceConfig(access_key="era-test", base_currency="EUR", start_date=None)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your Exchange Rates API access key. Check that the key is correct and that exchangeratesapi.io is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.source.validate_exchange_rates_api_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("era-test")
