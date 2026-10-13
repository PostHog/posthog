import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zuora import ZuoraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source import ZuoraSource


class TestZuoraSource:
    def setup_method(self):
        self.source = ZuoraSource()
        self.team_id = 123
        self.config = ZuoraSourceConfig(environment="us_production", client_id="cid", client_secret="sec")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source.validate_zuora_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "Invalid Zuora credentials" in (error_message or "")
        mock_validate.assert_called_once_with("us_production", "cid", "sec")
