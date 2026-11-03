import pytest

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, ReleaseStatus
from products.warehouse_sources.backend.temporal.data_imports.sources.census.source import CensusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.census import CensusSourceConfig


class TestCensusSource:
    def setup_method(self) -> None:
        self.source = CensusSource()
        self.team_id = 123
        self.config = CensusSourceConfig(api_key="census-key", region="us")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Census"
        assert config.label == "Census (Fivetran)"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.BETA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/census.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/census"

    @pytest.mark.parametrize(
        "api_version, expected_tables",
        [
            (None, {"syncs", "sync_runs", "sources", "destinations", "datasets"}),
            ("v1", {"syncs", "sync_runs", "sources", "destinations", "datasets", "workspaces"}),
            ("v2", {"syncs", "sync_runs", "sources", "destinations", "datasets"}),
        ],
    )
    def test_get_schemas_all_full_refresh(self, api_version: str | None, expected_tables: set[str]) -> None:
        # Census has no server-side timestamp filter on any list endpoint, so nothing supports
        # incremental sync. Workspaces have no V2 equivalent.
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)
        assert {schema.name for schema in schemas} == expected_tables
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []
