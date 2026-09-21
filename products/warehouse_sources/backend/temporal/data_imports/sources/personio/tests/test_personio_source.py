import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.personio import (
    PersonioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.source import PersonioSource


class TestPersonioSource:
    def setup_method(self):
        self.source = PersonioSource()
        self.team_id = 123
        self.config = PersonioSourceConfig(client_id="client-id", client_secret="client-secret")

    @pytest.mark.parametrize(
        "observed_error",
        [
            # Permanent OAuth2 token-exchange failures carry the framework's stable marker.
            f"HTTP 401 from the OAuth2 token endpoint: invalid_client {OAUTH2_PERMANENT_ERROR_MARKER}",
            f"HTTP 400 from the OAuth2 token endpoint {OAUTH2_PERMANENT_ERROR_MARKER}",
            "403 Client Error: Forbidden for url: https://api.personio.de/v2/persons?limit=50",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.personio.de/v2/persons",
            # A transient 429/5xx token error shares the endpoint phrasing but lacks the marker.
            "HTTP 503 from the OAuth2 token endpoint",
            # A mid-sync 401 on a data endpoint isn't a disable condition — the token is re-minted.
            "401 Client Error: Unauthorized for url: https://api.personio.de/v2/persons",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Incremental support tracks the settings catalog: only endpoints with a server-side
        # updated_at filter expose it. The salary-bands and cost-centers dimension lookups have no
        # timestamp field, so they must stay full-refresh — marking them incremental would emit an
        # updated_at param the API ignores while claiming to have filtered.
        for schema in schemas:
            expected_incremental = schema.name in INCREMENTAL_FIELDS
            assert schema.supports_incremental is expected_incremental
            assert schema.supports_append is expected_incremental

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Personio API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.personio.source.validate_personio_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.client_id, self.config.client_secret)
