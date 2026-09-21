from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.source import CoinMarketCapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coinmarketcap import (
    CoinMarketCapSourceConfig,
)


class TestCoinMarketCapSource:
    def setup_method(self) -> None:
        self.source = CoinMarketCapSource()
        self.team_id = 123
        self.config = CoinMarketCapSourceConfig(api_key="test-key")

    def test_get_schemas_offers_incremental_only_where_a_time_filter_drives_it(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        incremental = {s.name for s in schemas if s.supports_incremental}
        # Only global metrics has a `time_start` filter over a single series. Every other table is
        # either a current-state snapshot or a per-coin series the shared watermark can't bound.
        assert incremental == set(INCREMENTAL_FIELDS)
        assert {s.name for s in schemas if s.supports_append} == incremental
        assert all((s.incremental_fields == INCREMENTAL_FIELDS.get(s.name, [])) for s in schemas)

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
