import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source import CultureAmpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cultureamp import (
    CultureAmpSourceConfig,
)


class TestCultureAmpSource:
    def setup_method(self):
        self.source = CultureAmpSource()
        self.team_id = 123
        self.config = CultureAmpSourceConfig(client_id="cid", client_secret="sec", account_id="entity-1")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source.validate_culture_amp_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "employees read permission" in (error_message or "")
        mock_validate.assert_called_once_with("cid", "sec", "entity-1")
