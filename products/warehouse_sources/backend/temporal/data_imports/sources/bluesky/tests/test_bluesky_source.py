from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source import (
    PARTITION_FIELDS,
    PRIMARY_KEYS,
    BlueskySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)


class TestBlueskySource:
    def setup_method(self):
        self.source = BlueskySource()
        self.team_id = 123
        self.config = BlueskySourceConfig(actor="jay.bsky.team")

    def test_every_endpoint_has_primary_keys_declared(self):
        assert set(PRIMARY_KEYS) == set(ENDPOINTS)

    def test_partition_fields_only_cover_multi_row_endpoints(self):
        # Profile is a single row per sync; partitioning it isn't meaningful.
        assert "Profile" not in PARTITION_FIELDS
        assert set(PARTITION_FIELDS) == set(ENDPOINTS) - {"Profile"}
