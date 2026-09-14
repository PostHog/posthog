from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.source import CoinMarketCapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coinmarketcap import (
    CoinMarketCapSourceConfig,
)


class TestCoinMarketCapSource:
    def setup_method(self) -> None:
        self.source = CoinMarketCapSource()
        self.team_id = 123
        self.config = CoinMarketCapSourceConfig(api_key="test-key")

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Every CoinMarketCap "latest"/"map" endpoint is a current-state snapshot with no
        # server-side timestamp filter, so all schemas are full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["fiat_map"])
        assert len(schemas) == 1
        assert schemas[0].name == "fiat_map"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Every advertised endpoint should have a curated description so it isn't sent to the LLM.
        assert set(descriptions.keys()) == set(ENDPOINTS)
