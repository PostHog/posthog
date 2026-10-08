import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source import CrunchbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crunchbase import (
    CrunchbaseSourceConfig,
)


class TestCrunchbaseSource:
    def setup_method(self):
        self.source = CrunchbaseSource()
        self.team_id = 123
        self.config = CrunchbaseSourceConfig(api_key="user-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source.validate_crunchbase_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "Enterprise/Applications" in (error_message or "")
        mock_validate.assert_called_once_with(self.config.api_key)
