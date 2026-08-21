from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    ANNOTATIONS_ENDPOINT,
    COHORTS_ENDPOINT,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source import AmplitudeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplitude import (
    AmplitudeSourceConfig,
)

FULL_REFRESH_ENDPOINTS = [COHORTS_ENDPOINT, ANNOTATIONS_ENDPOINT]


class TestAmplitudeSource:
    def setup_method(self):
        self.source = AmplitudeSource()
        self.team_id = 123
        self.config = AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us")

    def test_events_endpoint_advertises_incremental(self):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == EVENTS_ENDPOINT)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"server_upload_time"}
        assert schema.description == "Only syncs the last 30 days on initial sync"
