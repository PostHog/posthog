import pytest

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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.themoviedb.org/3/movie/popular?api_key=x&page=1",
            "401 Client Error: Unauthorized for url: https://api.themoviedb.org/3/configuration",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error for url: https://api.themoviedb.org/3/movie/popular",
            "404 Client Error: Not Found for url: https://api.themoviedb.org/3/movie/0",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_canonical_descriptions_keyed_by_known_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Only documents endpoints that actually exist; partial coverage is allowed.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "movie_popular" in descriptions
