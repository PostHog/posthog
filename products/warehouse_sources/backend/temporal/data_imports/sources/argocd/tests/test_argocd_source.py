import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.source import ArgocdSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ArgocdSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestArgocdSource:
    def setup_method(self):
        self.source = ArgocdSource()
        self.team_id = 123
        self.config = ArgocdSourceConfig(host="https://argocd.example.com", api_token="tok", project=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ARGOCD

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Argocd"
        assert config.label == "Argo CD"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/argocd.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/argocd"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "api_token", "project"]

        host_field, token_field, project_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.required is True
        assert host_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

        assert isinstance(project_field, SourceFieldInputConfig)
        assert project_field.required is False

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "Argo CD host is not allowed",
            "Argo CD host must use HTTPS",
            "Argo CD API response exceeded the size limit",
            "Argo CD API response exceeded the download time limit",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Argo CD endpoint has a server-side timestamp filter, so nothing may advertise
        # incremental or append sync.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["applications"])
        assert [s.name for s in schemas] == ["applications"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.argocd.source.validate_argocd_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate):
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="applications")

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            self.config.host, self.config.api_token, "applications", self.team_id, self.config.project
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.argocd.source.argocd_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_argocd_source):
        config = ArgocdSourceConfig(host="https://argocd.example.com", api_token="tok", project="default")
        inputs = mock.MagicMock()
        inputs.schema_name = "applications"
        inputs.team_id = 42

        self.source.source_for_pipeline(config, inputs)

        kwargs = mock_argocd_source.call_args.kwargs
        assert kwargs["host"] == "https://argocd.example.com"
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "applications"
        assert kwargs["team_id"] == 42
        assert kwargs["project"] == "default"
