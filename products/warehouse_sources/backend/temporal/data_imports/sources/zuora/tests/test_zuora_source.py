import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zuora import ZuoraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.source import ZuoraSource


class TestZuoraSource:
    def setup_method(self):
        self.source = ZuoraSource()
        self.team_id = 123
        self.config = ZuoraSourceConfig(environment="us_production", client_id="cid", client_secret="sec")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://rest.zuora.com/oauth/token",
            "401 Client Error: Unauthorized for url: https://rest.sandbox.eu.zuora.com/oauth/token",
            "403 Client Error: Forbidden for url: https://rest.zuora.com/object-query/accounts",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_permanent_oauth2_token_error_is_non_retryable(self):
        # A permanent token-exchange failure carries the framework marker; it must map to an
        # actionable auth message rather than being retried forever.
        non_retryable_errors = self.source.get_non_retryable_errors()
        observed_error = f"HTTP 401 from the OAuth2 token endpoint: invalid_client {OAUTH2_PERMANENT_ERROR_MARKER}"
        matched = next(key for key in non_retryable_errors if key in observed_error)
        assert "authentication failed" in (non_retryable_errors[matched] or "")

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://rest.zuora.com/object-query/accounts"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every Object Query object filters server-side on updateddate.
        assert all(schema.supports_incremental for schema in schemas)
        assert all([f["field"] for f in schema.incremental_fields] == ["updatedDate"] for schema in schemas)
        assert {schema.name: schema.incremental_fields for schema in schemas} == INCREMENTAL_FIELDS

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
