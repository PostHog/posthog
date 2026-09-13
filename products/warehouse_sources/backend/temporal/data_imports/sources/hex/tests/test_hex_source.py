from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hex import HexSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.source import HexSource


class TestHexSource:
    def setup_method(self):
        self.source = HexSource()
        self.team_id = 123
        self.config = HexSourceConfig(api_key="hex_token", workspace_url=None)

    def test_workspace_url_is_a_connection_host_field(self):
        # Retargeting the workspace URL must force re-entry of the API token — without this an
        # editor could point the stored token at a host they control.
        assert self.source.connection_host_fields == ["workspace_url"]

    def test_get_schemas_returns_all_endpoints_full_refresh_only(self):
        # The Hex API has no server-side timestamp filter, so no endpoint may advertise
        # incremental or append sync.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hex.source.hex_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hex_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_hex_source.call_args.kwargs
        assert kwargs["api_key"] == "hex_token"
        assert kwargs["workspace_url"] is None
        assert kwargs["endpoint"] == "projects"
        assert kwargs["team_id"] == 42
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        # Full-refresh runs must not leak a stray watermark into the transport.
        assert kwargs["db_incremental_field_last_value"] is None
