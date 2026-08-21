from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.cloudability import (
    CloudabilityResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source import CloudabilitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCloudabilitySource:
    def setup_method(self):
        self.source = CloudabilitySource()
        self.team_id = 123
        self.config = CloudabilitySourceConfig(api_key="key", region="us", view_id=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CLOUDABILITY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Cloudability"
        assert config.category is not None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/cloudability.png"
        assert len(config.fields) == 3

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        region_field = config.fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

        view_id_field = config.fields[2]
        assert isinstance(view_id_field, SourceFieldInputConfig)
        assert view_id_field.name == "view_id"
        assert view_id_field.required is False
        assert view_id_field.secret is False

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "Unauthorized for url"])
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_no_endpoint_advertises_incremental(self, endpoint):
        # None of Cloudability's endpoints expose a server-side "modified since" filter.
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Views"])
        assert len(schemas) == 1
        assert schemas[0].name == "Views"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials. Check your API key and region."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.validate_cloudability_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CloudabilityResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.cloudability_source"
    )
    def test_source_for_pipeline_plumbs_inputs(self, mock_cloudability_source):
        mock_cloudability_source.return_value = SimpleNamespace(name="Views")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(schema_name="Views", team_id=self.team_id, job_id="job-1")

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_cloudability_source.assert_called_once_with(
            api_key="key",
            region="us",
            endpoint="Views",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
            view_id=None,
        )
        assert response is mock_cloudability_source.return_value

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.cloudability_source"
    )
    def test_source_for_pipeline_passes_blank_view_id_as_none(self, mock_cloudability_source):
        # An empty string from the form must not be sent to Cloudability as a literal viewId="".
        config = CloudabilitySourceConfig(api_key="key", region="eu", view_id="")
        mock_cloudability_source.return_value = SimpleNamespace(name="Anomalies")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(schema_name="Anomalies", team_id=self.team_id, job_id="job-2")

        self.source.source_for_pipeline(config, manager, cast(SourceInputs, inputs))

        assert mock_cloudability_source.call_args.kwargs["view_id"] is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.cloudability_source"
    )
    def test_source_for_pipeline_passes_configured_view_id(self, mock_cloudability_source):
        config = CloudabilitySourceConfig(api_key="key", region="us", view_id="42")
        mock_cloudability_source.return_value = SimpleNamespace(name="Anomalies")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(schema_name="Anomalies", team_id=self.team_id, job_id="job-3")

        self.source.source_for_pipeline(config, manager, cast(SourceInputs, inputs))

        assert mock_cloudability_source.call_args.kwargs["view_id"] == "42"
