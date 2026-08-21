import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.personio import (
    PersonioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.source import PersonioSource


class TestPersonioSource:
    def setup_method(self):
        self.source = PersonioSource()
        self.team_id = 123
        self.config = PersonioSourceConfig(client_id="client-id", client_secret="client-secret")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Personio API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.source.validate_personio_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.client_id, self.config.client_secret)
