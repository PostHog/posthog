import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source import AppsignalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appsignal import (
    AppsignalSourceConfig,
)


class TestAppsignalSource:
    def setup_method(self):
        self.source = AppsignalSource()
        self.team_id = 123
        self.config = AppsignalSourceConfig(api_token="api-token", app_id="app-id")

    def test_connection_host_fields_force_secret_reentry_on_app_change(self):
        # Changing app_id retargets the stored token at a different AppSignal app, so the update
        # serializer must require re-entering the secret — regressing this reopens that hole.
        assert self.source.connection_host_fields == ["app_id"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://appsignal.com/api/app-id/samples/errors.json",
            "403 Client Error: Forbidden for url: https://appsignal.com/graphql",
            "404 Client Error: Not Found for url: https://appsignal.com/api/app-id/markers.json",
            "AppSignal app not found: check that the app ID matches your AppSignal app",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://appsignal.com/api/app-id/samples.json",
        ],
    )
    def test_non_retryable_errors_do_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the REST endpoints expose a server-side time filter; the GraphQL incident
        # lists don't, so they stay full refresh.
        assert incremental == {"deploy_markers", "error_samples", "performance_samples"}

    def test_only_immutable_sample_tables_support_append(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["error_samples"].supports_append is True
        assert schemas["performance_samples"].supports_append is True
        # Deploy markers mutate after creation (exception counts accumulate) — merge only.
        assert schemas["deploy_markers"].supports_append is False
        assert schemas["exception_incidents"].supports_append is False

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["deploy_markers"].incremental_fields == INCREMENTAL_FIELDS["deploy_markers"]
        assert schemas["error_samples"].incremental_fields == INCREMENTAL_FIELDS["error_samples"]
        assert schemas["exception_incidents"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["error_samples"])
        assert [schema.name for schema in schemas] == ["error_samples"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AppSignal personal API token or app ID"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source.validate_appsignal_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token, self.config.app_id)
