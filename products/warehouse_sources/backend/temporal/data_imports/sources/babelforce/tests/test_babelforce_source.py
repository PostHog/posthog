import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source import BabelforceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.babelforce import (
    BabelforceSourceConfig,
)


class TestBabelforceSource:
    def setup_method(self):
        self.source = BabelforceSource()
        self.team_id = 123
        self.config = BabelforceSourceConfig(environment="services", access_id="access-id", access_token="token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Babelforce API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.validate_babelforce_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.environment, self.config.access_id, self.config.access_token)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.validate_babelforce_credentials"
    )
    def test_validate_credentials_rejects_bad_environment_without_probing(self, mock_validate):
        config = BabelforceSourceConfig(environment="evil.example.com", access_id="id", access_token="token")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        mock_validate.assert_not_called()
