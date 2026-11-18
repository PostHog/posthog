from products.warehouse_sources.sources.coinmarketcap._config import CoinMarketCapSourceConfig
from products.warehouse_sources.sources.coinmarketcap.settings import ENDPOINTS
from products.warehouse_sources.sources.coinmarketcap.source import CoinMarketCapSource


class TestCoinMarketCapSource:
    def setup_method(self) -> None:
        self.source = CoinMarketCapSource()
        self.team_id = 123
        self.config = CoinMarketCapSourceConfig(api_key="test-key")

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Every advertised endpoint should have a curated description so it isn't sent to the LLM.
        assert set(descriptions.keys()) == set(ENDPOINTS)
