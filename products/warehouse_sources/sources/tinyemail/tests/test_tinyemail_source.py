from products.warehouse_sources.sources.sdk import DataWarehouseSourceCategory, ReleaseStatus
from products.warehouse_sources.sources.tinyemail._config import TinyemailSourceConfig
from products.warehouse_sources.sources.tinyemail.settings import ENDPOINTS
from products.warehouse_sources.sources.tinyemail.source import TinyemailSource


class TestTinyemailSource:
    def setup_method(self) -> None:
        self.source = TinyemailSource()
        self.team_id = 123
        self.config = TinyemailSourceConfig(api_key="tinyemail-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name == "Tinyemail"
        assert config.label == "tinyEmail"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.BETA
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tinyemail"
        assert config.iconPath == "/static/services/tinyemail.png"
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_sync_modes(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Only the engagement report takes a server-side date range. Its recent rows change as
        # opens arrive, so it merges with a one-window overlap and never appends.
        for schema in schemas:
            assert schema.supports_append is False
            if schema.name == "new_subscriber_engagement":
                assert schema.supports_incremental is True
                assert [f["field"] for f in schema.incremental_fields] == ["date"]
                assert schema.default_incremental_lookback_seconds == 7 * 24 * 60 * 60
            else:
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []
