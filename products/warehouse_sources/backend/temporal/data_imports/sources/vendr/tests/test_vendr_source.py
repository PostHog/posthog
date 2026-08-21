from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vendr import VendrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.source import VendrSource


class TestVendrSource:
    def setup_method(self) -> None:
        self.source = VendrSource()
        self.team_id = 123
        self.config = VendrSourceConfig(api_key="vendr-key")

    @parameterized.expand(
        [
            ((True, None), True, None),
            ((False, 401), False, "Invalid Vendr API key"),
            ((False, 403), False, "Invalid Vendr API key"),
            ((False, None), False, "Invalid Vendr API key"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.vendr.source.validate_vendr_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message, mock_validate) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("vendr-key")
