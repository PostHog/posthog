import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source import CommercetoolsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.commercetools import (
    CommercetoolsSourceConfig,
)


class TestCommercetoolsSource:
    def setup_method(self):
        self.source = CommercetoolsSource()
        self.team_id = 123
        self.config = CommercetoolsSourceConfig(
            region="us-central1.gcp",
            project_key="my-project",
            client_id="client-id",
            client_secret="client-secret",
        )

    def test_connection_host_fields_cover_region_and_project(self):
        assert self.source.connection_host_fields == ["region", "project_key"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://auth.us-central1.gcp.commercetools.com/oauth/token",
            "400 Client Error: Bad Request for url: https://auth.europe-west1.gcp.commercetools.com/oauth/token",
            "403 Client Error: Forbidden for url: https://api.us-central1.gcp.commercetools.com/my-project/orders",
            "404 Client Error: Not Found for url: https://api.us-central1.gcp.commercetools.com/nope/orders",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.us-central1.gcp.commercetools.com/my-project/orders",
            # Mid-sync 401s on the API host are handled by token re-mint, not disable.
            "401 Client Error: Unauthorized for url: https://api.us-central1.gcp.commercetools.com/my-project/orders",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every queryable resource supports lastModifiedAt predicates.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid commercetools API client credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source.validate_commercetools_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us-central1.gcp", "my-project", "client-id", "client-secret")
