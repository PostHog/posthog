import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source import BabelforceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.babelforce import (
    BabelforceSourceConfig,
)


class TestBabelforceSource:
    def setup_method(self):
        self.source = BabelforceSource()
        self.team_id = 123
        self.config = BabelforceSourceConfig(environment="services", access_id="access-id", access_token="token")

    def test_environment_is_a_connection_host_field(self):
        # `environment` decides which host receives the stored token; changing it must force
        # the editor to re-enter the token or the credential could be exfiltrated.
        assert self.source.connection_host_fields == ["environment"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://services.babelforce.com/api/v2/calls/reporting?max=100",
            "403 Client Error: Forbidden for url: https://us-east.babelforce.com/api/v2/agents",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://services.babelforce.com/api/v2/calls/reporting"
            for key in non_retryable_errors
        )

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only call reporting documents a server-side dateCreated filter.
        assert incremental == {"calls"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Babelforce API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.validate_babelforce_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.environment, self.config.access_id, self.config.access_token)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source.validate_babelforce_credentials"
    )
    def test_validate_credentials_rejects_bad_environment_without_probing(self, mock_validate):
        config = BabelforceSourceConfig(environment="evil.example.com", access_id="id", access_token="token")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        mock_validate.assert_not_called()
