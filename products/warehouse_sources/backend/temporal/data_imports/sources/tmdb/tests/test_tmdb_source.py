from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tmdb import TMDbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tmdb.source import TMDbSource


class TestTMDbSource:
    def setup_method(self) -> None:
        self.source = TMDbSource()
        self.team_id = 123
        self.config = TMDbSourceConfig(api_key="tmdb-key")

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # TMDB v3 exposes no server-side updated-after filter, so every schema is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_canonical_descriptions_keyed_by_known_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Only documents endpoints that actually exist; partial coverage is allowed.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "movie_popular" in descriptions
