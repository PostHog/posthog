import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pipeliner import (
    PipelinerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source import PipelinerSource


class TestPipelinerSource:
    def setup_method(self):
        self.source = PipelinerSource()
        self.team_id = 123
        self.config = PipelinerSourceConfig(
            service_url="us-east.api.pipelinersales.com",
            space_id="space-1",
            username="api-user",
            password="api-pass",
        )

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Pipeliner"
        assert config.label == "Pipeliner"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/pipeliner.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["service_url", "space_id", "username", "password"]

        # Both halves of the generated API key pair are credentials — a non-secret one would be
        # returned in job_inputs to anyone with source read access.
        for credential_field in config.fields[-2:]:
            assert isinstance(credential_field, SourceFieldInputConfig)
            assert credential_field.type == SourceFieldInputConfigType.PASSWORD
            assert credential_field.secret is True
            assert credential_field.required is True

    def test_service_url_is_a_connection_host_field(self):
        # Retargeting the service URL must force re-entry of the API key pair — without this an
        # editor could point the stored credentials at a server they control and exfiltrate them.
        assert "service_url" in self.source.connection_host_fields

    def test_get_schemas_returns_all_endpoints_with_incremental_support(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert [f["field"] for f in schema.incremental_fields] == ["modified"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["accounts"])
        assert len(schemas) == 1
        assert schemas[0].name == "accounts"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_get_documented_tables_lists_static_catalog(self):
        tables = {t["name"] for t in self.source.get_documented_tables()}
        assert tables == set(ENDPOINTS)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source.pipeliner_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pipeliner_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "opportunities"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        inputs.incremental_field = "modified"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_pipeliner_source.call_args.kwargs
        assert kwargs["service_url"] == "us-east.api.pipelinersales.com"
        assert kwargs["space_id"] == "space-1"
        assert kwargs["username"] == "api-user"
        assert kwargs["password"] == "api-pass"
        assert kwargs["endpoint"] == "opportunities"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01 00:00:00"
        assert kwargs["incremental_field"] == "modified"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source.pipeliner_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_pipeliner_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_pipeliner_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "unknown"

        with pytest.raises(ValueError, match="Unknown Pipeliner schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
