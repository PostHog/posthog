import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.source import AsanaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asana import AsanaSourceConfig


class TestAsanaSource:
    def setup_method(self):
        self.source = AsanaSource()
        self.team_id = 123
        self.config = AsanaSourceConfig(access_token="1/abc")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Asana personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.asana.source.validate_asana_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)
