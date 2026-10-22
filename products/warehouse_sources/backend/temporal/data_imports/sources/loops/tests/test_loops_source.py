from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loops import LoopsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.source import LoopsSource


class TestLoopsSource:
    def setup_method(self) -> None:
        self.source = LoopsSource()
        self.team_id = 123
        self.config = LoopsSourceConfig(api_key="test-key")

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Loops list endpoints have no server-side timestamp filters, so advertising
        # incremental sync would silently degrade to a broken full scan.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_canonical_descriptions_cover_only_known_endpoints(self) -> None:
        # A description keyed by a name `get_schemas` never returns is dead metadata
        # (typo'd endpoint or a rename that missed this file).
        assert set(self.source.get_canonical_descriptions().keys()) <= set(ENDPOINTS)
