import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openexchangerates import (
    OpenExchangeRatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source import (
    OpenExchangeRatesSource,
)


class TestOpenExchangeRatesSource:
    def setup_method(self) -> None:
        self.source = OpenExchangeRatesSource()
        self.team_id = 123
        self.config = OpenExchangeRatesSourceConfig(app_id="oxr-test", base_currency="USD", start_date=None)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your Open Exchange Rates App ID. Check that the App ID is correct and that openexchangerates.org is reachable.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.source.validate_open_exchange_rates_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("oxr-test")
