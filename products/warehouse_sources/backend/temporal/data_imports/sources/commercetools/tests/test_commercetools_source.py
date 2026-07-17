import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.commercetools import (
    CommercetoolsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source import CommercetoolsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CommercetoolsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


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

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.COMMERCETOOLS

    def test_connection_host_fields_cover_region_and_project(self):
        assert self.source.connection_host_fields == ["region", "project_key"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Commercetools"
        assert config.label == "commercetools"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/commercetools.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["region", "project_key", "client_id", "client_secret"]

    def test_region_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us-central1.gcp"
        assert {option.value for option in region_field.options} == {
            "us-central1.gcp",
            "us-east-2.aws",
            "europe-west1.gcp",
            "eu-central-1.aws",
            "australia-southeast1.gcp",
        }

    def test_client_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

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

    def test_schemas_advertise_last_modified_cursor(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["orders"].incremental_fields == INCREMENTAL_FIELDS["orders"]
        assert [f["field"] for f in schemas["orders"].incremental_fields] == ["lastModifiedAt"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CommercetoolsResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source.commercetools_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_ct_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_ct_source.assert_called_once()
        kwargs = mock_ct_source.call_args.kwargs
        assert kwargs["region"] == "us-central1.gcp"
        assert kwargs["project_key"] == "my-project"
        assert kwargs["client_id"] == "client-id"
        assert kwargs["client_secret"] == "client-secret"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.000Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source.commercetools_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_ct_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_ct_source.call_args.kwargs["db_incremental_field_last_value"] is None
