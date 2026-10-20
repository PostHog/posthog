import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.taboola import (
    TaboolaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source import TaboolaSource


class TestTaboolaSource:
    def setup_method(self):
        self.source = TaboolaSource()
        self.team_id = 123
        self.config = TaboolaSourceConfig(client_id="cid", client_secret="sec", account_id="acct")

    def test_connection_host_fields_includes_account_id(self):
        assert self.source.connection_host_fields == ["account_id"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source.validate_taboola_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Taboola credentials"
        mock_validate.assert_called_once_with("cid", "sec")
