from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px import (
    GainsightPxResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source import GainsightPxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GainsightPxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGainsightPxSource:
    def setup_method(self):
        self.source = GainsightPxSource()
        self.team_id = 123
        self.config = GainsightPxSourceConfig(api_key="key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GAINSIGHTPX

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "GainsightPx"
        assert config.label == "Gainsight PX"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/gainsight_px.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/gainsight-px"
        assert len(config.fields) == 2

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
        assert {option.value for option in region_field.options} == {"us", "eu", "us2"}

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_is_full_refresh(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        # No Gainsight PX list endpoint exposes a server-side "updated since" filter, so every
        # table must be full refresh — advertising incremental would silently corrupt the cursor.
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_advertises_a_primary_key(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.detected_primary_keys

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_lists_tables_without_credentials(self):
        # A static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        # Canonical descriptions should flow into the documented catalog.
        users = next(t for t in tables if t["name"] == "users")
        assert users["description"]
        assert users["sync_methods"] == ["Full refresh"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source.validate_gainsight_px_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GainsightPxResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source.gainsight_px_source"
    )
    def test_source_for_pipeline_plumbs_inputs(self, mock_gainsight_source):
        mock_gainsight_source.return_value = SimpleNamespace(name="users")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        logger = mock.MagicMock()
        inputs = SimpleNamespace(schema_name="users", team_id=self.team_id, job_id="job-1", logger=logger)

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_gainsight_source.assert_called_once_with(
            api_key="key",
            region="us",
            endpoint="users",
            logger=logger,
            resumable_source_manager=manager,
        )
        assert response is mock_gainsight_source.return_value
