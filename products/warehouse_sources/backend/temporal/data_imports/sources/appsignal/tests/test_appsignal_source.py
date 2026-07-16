import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal import AppsignalResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source import AppsignalSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppsignalSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAppsignalSource:
    def setup_method(self):
        self.source = AppsignalSource()
        self.team_id = 123
        self.config = AppsignalSourceConfig(api_token="api-token", app_id="app-id")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.APPSIGNAL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Appsignal"
        assert config.label == "AppSignal"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/appsignal.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token", "app_id"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppsignalResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source.appsignal_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_appsignal_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "error_samples"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_appsignal_source.call_args.kwargs
        assert kwargs["api_token"] == "api-token"
        assert kwargs["app_id"] == "app-id"
        assert kwargs["endpoint"] == "error_samples"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.source.appsignal_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_appsignal_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "exception_incidents"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_appsignal_source.call_args.kwargs["db_incremental_field_last_value"] is None
