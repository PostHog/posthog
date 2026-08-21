import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ortto import OrttoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source import OrttoSource


class TestOrttoSource:
    def setup_method(self):
        self.source = OrttoSource()
        self.team_id = 123
        self.config = OrttoSourceConfig(api_key="key", region="eu")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source.validate_ortto_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Ortto credentials"
        mock_validate.assert_called_once_with("eu", "key")
