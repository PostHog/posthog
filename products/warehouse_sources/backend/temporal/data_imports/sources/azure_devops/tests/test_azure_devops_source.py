import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
    AZURE_DEVOPS_VERSION_7_2,
    AZURE_DEVOPS_VERSION_LEGACY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source import AzureDevOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azuredevops import (
    AzureDevOpsSourceConfig,
)


class TestAzureDevOpsSource:
    def setup_method(self):
        self.source = AzureDevOpsSource()
        self.team_id = 123
        self.config = AzureDevOpsSourceConfig(organization="myorg", personal_access_token="pat")

    def test_connection_host_fields_includes_organization(self):
        # The PAT is sent to dev.azure.com/<organization>, so retargeting the
        # organization must force re-entry of the token.
        assert self.source.connection_host_fields == ["organization"]

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

    @pytest.mark.parametrize(
        "probe_result",
        [
            (True, None),
            (
                False,
                "Azure DevOps denied access. Please check that your personal access token has read scopes for this data.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source.validate_azure_devops_credentials"
    )
    def test_validate_credentials_passes_probe_result_through(self, mock_validate, probe_result):
        mock_validate.return_value = probe_result

        # The specific failure reason from the probe must reach the caller unchanged, not be
        # collapsed into a single generic message.
        assert self.source.validate_credentials(self.config, self.team_id) == probe_result
        # No pin at creation time resolves to default_version.
        mock_validate.assert_called_once_with("myorg", "pat", AZURE_DEVOPS_VERSION_7_2)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source.azure_devops_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_ado_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "work_item_revisions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        inputs.api_version = AZURE_DEVOPS_VERSION_7_2
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_ado_source.assert_called_once()
        kwargs = mock_ado_source.call_args.kwargs
        assert kwargs["organization"] == "myorg"
        assert kwargs["personal_access_token"] == "pat"
        assert kwargs["endpoint"] == "work_item_revisions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["api_version"] == AZURE_DEVOPS_VERSION_7_2
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @pytest.mark.parametrize(
        "pinned, expected",
        [
            (None, AZURE_DEVOPS_VERSION_7_2),
            ("", AZURE_DEVOPS_VERSION_7_2),
            (AZURE_DEVOPS_VERSION_LEGACY, AZURE_DEVOPS_VERSION_LEGACY),
            (AZURE_DEVOPS_VERSION_7_2, AZURE_DEVOPS_VERSION_7_2),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.source.azure_devops_source"
    )
    def test_source_for_pipeline_resolves_the_pin(self, mock_ado_source, pinned, expected):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.api_version = pinned

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_ado_source.call_args.kwargs["api_version"] == expected

    def test_default_version_is_the_new_ga_version(self):
        # New sources start on 7.2; the legacy label stays supported so existing pins keep working.
        assert self.source.default_version == AZURE_DEVOPS_VERSION_7_2
        assert set(self.source.supported_versions) == {AZURE_DEVOPS_VERSION_LEGACY, AZURE_DEVOPS_VERSION_7_2}

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
