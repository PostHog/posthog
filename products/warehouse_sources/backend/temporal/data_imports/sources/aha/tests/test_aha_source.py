import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.aha.source import AhaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aha import AhaSourceConfig

# Endpoints whose Aha! list action exposes the server-side `updated_since` filter.
_INCREMENTAL_ENDPOINTS = {"products", "features", "epics", "initiatives", "ideas", "todos"}
_FULL_REFRESH_ENDPOINTS = {"goals", "users"}


class TestAhaSource:
    def setup_method(self):
        self.source = AhaSource()
        self.team_id = 123
        self.config = AhaSourceConfig(subdomain="acme", api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Aha! API key"),
            ((False, 403), False, "Could not connect to Aha! with the provided account domain and API key"),
            ((False, None), False, "Could not connect to Aha! with the provided account domain and API key"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aha.source.validate_aha_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aha.source.validate_aha_credentials")
    def test_validate_credentials_surfaces_bad_subdomain(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Aha! account domain: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Aha! account domain" in (error_message or "")
