import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uservoice import (
    UservoiceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import ENDPOINTS
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

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Uservoice"
        assert config.label == "UserVoice"
        # A finished source ships visible with a soft ALPHA label, never hidden.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/uservoice"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "api_key"]

    def test_subdomain_listed_as_connection_host_field(self):
        # The token is sent to <subdomain>.uservoice.com, so retargeting the subdomain must re-require it.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.uservoice.com/api/v2/admin/suggestions?per_page=100",
            "403 Client Error: Forbidden for url: https://acme.uservoice.com/api/v2/admin/tickets?per_page=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.uservoice.com/api/v2/admin/suggestions",
            "500 Server Error: Internal Server Error for url: https://acme.uservoice.com/api/v2/admin/suggestions",
            "HTTPSConnectionPool(host='acme.uservoice.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

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
