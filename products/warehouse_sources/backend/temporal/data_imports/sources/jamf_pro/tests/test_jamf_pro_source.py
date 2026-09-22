import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jamfpro import (
    JamfProAuthMethodConfig,
    JamfProSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source import JamfProSource


class TestJamfProSource:
    def setup_method(self):
        self.source = JamfProSource()
        self.team_id = 123
        self.config = JamfProSourceConfig(
            instance_url="example.jamfcloud.com",
            auth_method=JamfProAuthMethodConfig(
                selection="client_credentials", client_id="cid", client_secret="secret"
            ),
        )

    def test_connection_host_fields_covers_instance_url(self):
        # Without this, an org member could retarget the instance URL at a server they control
        # and exfiltrate the preserved credentials.
        assert self.source.connection_host_fields == ["instance_url"]

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_schema_sync_modes(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        # Only computer inventory documents a server-side RSQL timestamp filter; everything else
        # is full-refresh. Inventory records mutate in place, so append mode is never offered.
        assert schemas[endpoint].supports_incremental is (endpoint == "computers")
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["computers"])
        assert [s.name for s in schemas] == ["computers"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source.jamf_pro_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_jamf_pro_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "computers"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_jamf_pro_source.call_args.kwargs
        assert kwargs["host"] == "example.jamfcloud.com"
        assert kwargs["credentials"].client_id == "cid"
        assert kwargs["endpoint"] == "computers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source.jamf_pro_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_jamf_pro_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "buildings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_jamf_pro_source.call_args.kwargs["db_incremental_field_last_value"] is None
