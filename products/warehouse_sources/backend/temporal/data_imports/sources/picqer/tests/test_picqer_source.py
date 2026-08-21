import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.picqer import PicqerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source import PicqerSource

# Endpoints whose Picqer list action exposes a genuine update-based `updated_after` filter.
_INCREMENTAL_ENDPOINTS = {"purchaseorders", "returns"}
_FULL_REFRESH_ENDPOINTS = set(ENDPOINTS) - _INCREMENTAL_ENDPOINTS


class TestPicqerSource:
    def setup_method(self):
        self.source = PicqerSource()
        self.team_id = 123
        self.config = PicqerSourceConfig(account_name="acme", api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            # 403 = valid key, insufficient scope — accepted at source-create (per-table scope reported separately).
            ((True, 403), True, None),
            ((False, 401), False, "Invalid Picqer API key"),
            ((False, None), False, "Could not connect to Picqer with the provided account name and API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source.validate_picqer_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source.validate_picqer_credentials"
    )
    def test_validate_credentials_surfaces_bad_account(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Picqer account: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Picqer account" in (error_message or "")
