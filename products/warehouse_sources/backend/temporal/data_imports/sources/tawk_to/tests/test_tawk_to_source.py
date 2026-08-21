import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tawkto import TawkToSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source import TawkToSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source"


class TestTawkToSource:
    def setup_method(self):
        self.source = TawkToSource()
        self.team_id = 123
        self.config = TawkToSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid tawk.to API key"),
        ],
    )
    @mock.patch(f"{MODULE}.validate_tawk_to_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
