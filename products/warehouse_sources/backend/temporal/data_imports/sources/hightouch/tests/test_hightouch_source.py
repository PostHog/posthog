from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, ReleaseStatus
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hightouch import (
    HightouchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.settings import (
    ENDPOINTS,
    SYNC_RUNS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.source import HightouchSource


class TestHightouchSource:
    def setup_method(self) -> None:
        self.source = HightouchSource()
        self.team_id = 123
        self.config = HightouchSourceConfig(api_key="hightouch-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Hightouch"
        assert config.label == "Hightouch"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.GA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/hightouch.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hightouch"

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Config tables have no server-side timestamp filter, so they are full refresh only.
        for name in ("syncs", "models", "sources", "destinations"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

        # sync_runs supports incremental via the server-side `after` filter on startedAt,
        # and is merge-only because in-progress runs mutate and the lookback re-reads them.
        assert schemas["sync_runs"].supports_incremental is True
        assert schemas["sync_runs"].supports_append is False
        assert [f["field"] for f in schemas["sync_runs"].incremental_fields] == ["startedAt"]
        assert schemas["sync_runs"].default_incremental_lookback_seconds == SYNC_RUNS_LOOKBACK_SECONDS
