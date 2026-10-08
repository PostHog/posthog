from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moxie import MoxieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.source import MoxieSource


class TestMoxieSource:
    def setup_method(self) -> None:
        self.source = MoxieSource()
        self.team_id = 123
        self.config = MoxieSourceConfig(base_url="https://pod00.withmoxie.dev/api/public", api_key="test_key")

    def test_connection_host_fields(self) -> None:
        # base_url carries the API key's destination, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["base_url"]

    def test_canonical_descriptions_keyed_by_endpoint_names(self) -> None:
        # A renamed endpoint would silently orphan its curated descriptions.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
