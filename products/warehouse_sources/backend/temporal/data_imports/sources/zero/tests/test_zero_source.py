import pytest
from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zero import ZeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.settings import ENDPOINT_CONFIGS
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.source import ZeroSource

INCREMENTAL_ENDPOINTS = {name for name, config in ENDPOINT_CONFIGS.items() if config.incremental_fields}


class TestZeroSource:
    def setup_method(self) -> None:
        self.source = ZeroSource()
        self.team_id = 123
        self.config = ZeroSourceConfig(api_key="api_test")

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zero.source.validate_zero_credentials"
    )
    def test_validate_credentials(self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("api_test")
