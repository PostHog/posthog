from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    Rapid7InsightvmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm import (
    Rapid7InsightvmResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.source import (
    Rapid7InsightvmSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.source"


class TestRapid7InsightvmSource:
    def setup_method(self):
        self.source = Rapid7InsightvmSource()
        self.team_id = 123
        self.config = Rapid7InsightvmSourceConfig(api_key="key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RAPID7INSIGHTVM

    def test_get_source_config_is_released_alpha(self):
        config = self.source.get_source_config
        # Guards against the scaffold's `unreleasedSource=True` (which hides the connector entirely)
        # regressing back in — a finished source must be visible.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True

        region_field = fields[1]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.name == "region"
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu", "ca", "au", "ap", "jp"}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    def test_non_retryable_errors_include_auth(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint advertises incremental — the v4 timestamp filter is unverified, so all ship full refresh.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["assets"])
        assert [schema.name for schema in schemas] == ["assets"]

    def test_validate_credentials_plumbs_to_transport(self):
        with mock.patch(f"{SOURCE}.validate_rapid7_insightvm_credentials", return_value=(True, None)) as mock_validate:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert message is None
        mock_validate.assert_called_once_with("key", "us")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is Rapid7InsightvmResumeConfig

    def test_source_for_pipeline_plumbs_inputs(self):
        manager = mock.MagicMock(spec=ResumableSourceManager)
        logger = mock.MagicMock()
        inputs = SimpleNamespace(schema_name="assets", team_id=self.team_id, job_id="job-1", logger=logger)

        with mock.patch(f"{SOURCE}.rapid7_insightvm_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_source.assert_called_once_with(
            api_key="key",
            region="us",
            endpoint="assets",
            logger=logger,
            resumable_source_manager=manager,
        )
