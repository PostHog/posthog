import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OctopusDeploySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.octopus_deploy import (
    OctopusDeployResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.source import OctopusDeploySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOctopusDeploySource:
    def setup_method(self):
        self.source = OctopusDeploySource()
        self.team_id = 123
        self.config = OctopusDeploySourceConfig(host="https://my-org.octopus.app", api_key="API-KEY")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OCTOPUSDEPLOY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "OctopusDeploy"
        assert config.label == "Octopus Deploy"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/octopus_deploy.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "api_key"]

        host_field, key_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.secret is False

        assert isinstance(key_field, SourceFieldInputConfig)
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("spaces", False),
            ("projects", False),
            ("releases", False),
            ("deployments", False),
            ("tasks", True),
            ("events", True),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deployments"])
        assert len(schemas) == 1
        assert schemas[0].name == "deployments"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Octopus Deploy API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.source.validate_octopus_deploy_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="deployments")

        assert result == mock_return
        mock_validate.assert_called_once_with(self.config.host, self.config.api_key, "deployments", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OctopusDeployResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.source.octopus_deploy_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+00:00"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["host"] == "https://my-org.octopus.app"
        assert kwargs["api_key"] == "API-KEY"
        assert kwargs["endpoint"] == "tasks"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00+00:00"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.source.octopus_deploy_source"
    )
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "deployments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
