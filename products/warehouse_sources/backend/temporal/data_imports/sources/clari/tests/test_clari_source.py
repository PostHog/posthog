import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.clari.source import ClariSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clari import ClariSourceConfig


class TestClariSource:
    def setup_method(self):
        self.source = ClariSource()
        self.team_id = 123
        self.config = ClariSourceConfig(api_key="key", forecast_id="fc-1")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clari.source.validate_clari_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Clari credentials"
        mock_validate.assert_called_once_with("key")
