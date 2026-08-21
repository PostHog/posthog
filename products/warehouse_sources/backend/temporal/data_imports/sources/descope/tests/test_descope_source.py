import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.descope.source import DescopeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.descope import (
    DescopeSourceConfig,
)


class TestDescopeSource:
    def setup_method(self):
        self.source = DescopeSource()
        self.team_id = 123
        self.config = DescopeSourceConfig(project_id="P2abc", management_key="mgmt-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.descope.source.validate_descope_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message
        mock_validate.assert_called_once_with(self.config.project_id, self.config.management_key)
