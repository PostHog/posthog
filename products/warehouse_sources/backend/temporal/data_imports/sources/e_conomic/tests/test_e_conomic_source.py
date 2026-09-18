import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source import EConomicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.economic import (
    EConomicSourceConfig,
)

INCREMENTAL_ENDPOINTS = {"customers", "products", "invoices_booked"}


class TestECONomicSource:
    def setup_method(self) -> None:
        self.source = EConomicSource()
        self.team_id = 123
        self.config = EConomicSourceConfig(app_secret_token="secret", agreement_grant_token="grant")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @pytest.mark.parametrize(
        "is_valid, expected_valid, expected_has_message",
        [(True, True, False), (False, False, True)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source.validate_e_conomic_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        is_valid: bool,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = is_valid
        valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.app_secret_token, self.config.agreement_grant_token)
