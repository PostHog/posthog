from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.source import CortexSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cortex import CortexSourceConfig


class TestCortexSource:
    def setup_method(self) -> None:
        self.source = CortexSource()
        self.team_id = 123
        self.config = CortexSourceConfig(api_key="cx_key")

    def test_source_is_released_not_hidden(self) -> None:
        # A finished source must be visible: `unreleasedSource` hides it from every user.
        assert not self.source.get_source_config.unreleasedSource

    def test_only_custom_events_syncs_incrementally(self) -> None:
        # `startTime` on the custom event stream is the only server-side time filter Cortex
        # documents; every other list endpoint has to be re-read in full.
        incremental = {
            schema.name for schema in self.source.get_schemas(self.config, self.team_id) if schema.supports_incremental
        }
        assert incremental == {"custom_events"}

    def test_full_refresh_schemas_advertise_no_cursor(self) -> None:
        for schema in self.source.get_schemas(self.config, self.team_id):
            if schema.name == "custom_events":
                continue
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True
