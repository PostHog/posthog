from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testrail import (
    TestrailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.settings import (
    ENDPOINTS,
    TESTRAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.source import TestrailSource


class TestTestrailSource:
    def setup_method(self) -> None:
        self.source = TestrailSource()
        self.team_id = 123
        self.config = TestrailSourceConfig(subdomain="acme", username="qa@acme.com", api_key="testrail-key")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to `<subdomain>.testrail.io`; without this, an editor could
        # retarget the subdomain and exfiltrate the preserved key.
        assert self.source.connection_host_fields == ["subdomain"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.testrail.source.testrail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "cases"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["username"] == "qa@acme.com"
        assert kwargs["api_key"] == "testrail-key"
        assert kwargs["endpoint"] == "cases"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.testrail.source.testrail_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left on the schema must not leak into a full-refresh sync.
        inputs = mock.MagicMock()
        inputs.schema_name = "cases"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        # TestRail record IDs are instance-global; a non-unique key would multi-match on merge.
        assert all(config.primary_keys == ["id"] for config in TESTRAIL_ENDPOINTS.values())
        assert set(TESTRAIL_ENDPOINTS) == set(ENDPOINTS)
