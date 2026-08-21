import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.source import AssemblyAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.assemblyai import (
    AssemblyAISourceConfig,
)


class TestAssemblyAISource:
    def setup_method(self):
        self.source = AssemblyAISource()
        self.team_id = 123
        self.config = AssemblyAISourceConfig(api_key="key", region="us")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AssemblyAI API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.source.validate_assemblyai_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)
