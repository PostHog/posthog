from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gladly import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import (
    REPORT_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source import GladlySource


class TestGladlySource:
    def setup_method(self):
        self.source = GladlySource()
        self.team_id = 123
        self.config = GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token")

    def test_conversations_schema_defaults_to_a_restatement_lookback(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        # Conversation-report rows restate in place, so only that schema
        # re-reads a trailing window on incremental runs.
        lookbacks = {schema.name: schema.default_incremental_lookback_seconds for schema in schemas}
        assert lookbacks.pop("conversations") == REPORT_INCREMENTAL_LOOKBACK_SECONDS
        assert all(seconds is None for seconds in lookbacks.values())
