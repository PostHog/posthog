import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uservoice import (
    UservoiceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.source import UservoiceSource

_INCREMENTAL_ENDPOINTS = {
    "suggestions",
    "forums",
    "users",
    "comments",
    "notes",
    "nps_ratings",
    "tickets",
    "ticket_messages",
}
_FULL_REFRESH_ENDPOINTS = {"suggestion_statuses", "labels"}


class TestUservoiceSource:
    def setup_method(self):
        self.source = UservoiceSource()
        self.team_id = 123
        self.config = UservoiceSourceConfig(subdomain="acme", api_key="token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid UserVoice API token"),
            ((False, 403), False, "Could not connect to UserVoice with the provided subdomain and API token"),
            ((False, None), False, "Could not connect to UserVoice with the provided subdomain and API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.source.validate_uservoice_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("acme", "token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.source.validate_uservoice_credentials"
    )
    def test_validate_credentials_surfaces_bad_subdomain(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid UserVoice account subdomain: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid UserVoice account subdomain" in (error_message or "")
