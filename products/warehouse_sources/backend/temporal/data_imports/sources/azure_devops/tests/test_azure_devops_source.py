import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
    AzureDevOpsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source import AzureDevOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AzureDevOpsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAzureDevOpsSource:
    def setup_method(self):
        self.source = AzureDevOpsSource()
        self.team_id = 123
        self.config = AzureDevOpsSourceConfig(organization="myorg", personal_access_token="pat")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.AZUREDEVOPS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "AzureDevOps"
        assert config.label == "Azure DevOps"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/azure_devops.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["organization", "personal_access_token"]

    def test_connection_host_fields_includes_organization(self):
        # The PAT is sent to dev.azure.com/<organization>, so retargeting the
        # organization must force re-entry of the token.
        assert self.source.connection_host_fields == ["organization"]

    def test_pat_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "personal_access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Azure DevOps returned a sign-in page (203) — the personal access token is invalid or expired.",
            "401 Client Error: Unauthorized for url: https://dev.azure.com/myorg/_apis/projects",
            "403 Client Error: Forbidden for url: https://dev.azure.com/myorg/Alpha/_apis/build/builds",
            "404 Client Error: Not Found for url: https://dev.azure.com/nope/_apis/projects",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://dev.azure.com/myorg/_apis/projects",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"builds", "pull_requests", "work_item_revisions"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["builds"].incremental_fields == INCREMENTAL_FIELDS["builds"]
        assert [f["field"] for f in schemas["work_item_revisions"].incremental_fields] == ["changed_date"]
        assert schemas["projects"].incremental_fields == []
        assert schemas["projects"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["builds"])
        assert len(schemas) == 1
        assert schemas[0].name == "builds"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Azure DevOps credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source.validate_azure_devops_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("myorg", "pat")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AzureDevOpsResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source.azure_devops_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_ado_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "work_item_revisions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_ado_source.assert_called_once()
        kwargs = mock_ado_source.call_args.kwargs
        assert kwargs["organization"] == "myorg"
        assert kwargs["personal_access_token"] == "pat"
        assert kwargs["endpoint"] == "work_item_revisions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source.azure_devops_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_ado_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_ado_source.call_args.kwargs["db_incremental_field_last_value"] is None
