from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pexels import PexelsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source import PexelsSource


class TestPexelsSource:
    def setup_method(self) -> None:
        self.source = PexelsSource()
        self.team_id = 123

    def test_schemas_without_query_exclude_search_tables(self) -> None:
        config = PexelsSourceConfig(api_key="k", search_query=None)
        names = {s.name for s in self.source.get_schemas(config, self.team_id)}
        assert names == {"curated_photos", "popular_videos", "featured_collections", "my_collections"}

    @parameterized.expand([("empty_string", ""), ("whitespace", "   ")])
    def test_blank_query_excludes_search_tables(self, _name: str, query: str) -> None:
        config = PexelsSourceConfig(api_key="k", search_query=query)
        names = {s.name for s in self.source.get_schemas(config, self.team_id)}
        assert "search_photos" not in names
        assert "search_videos" not in names

    def test_schemas_with_query_include_search_tables(self) -> None:
        config = PexelsSourceConfig(api_key="k", search_query="nature")
        names = {s.name for s in self.source.get_schemas(config, self.team_id)}
        assert {"search_photos", "search_videos"} <= names

    def test_all_schemas_are_full_refresh_only(self) -> None:
        # Pexels has no server-side timestamp filter, so no table may advertise incremental/append —
        # doing so would silently corrupt syncs since there's no cursor to filter on.
        config = PexelsSourceConfig(api_key="k", search_query="nature")
        for schema in self.source.get_schemas(config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_schemas_names_filter(self) -> None:
        config = PexelsSourceConfig(api_key="k", search_query=None)
        schemas = self.source.get_schemas(config, self.team_id, names=["curated_photos"])
        assert [s.name for s in schemas] == ["curated_photos"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True; the public-docs catalog is built from a placeholder
        # config with no I/O and must not be empty.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == {
            "curated_photos",
            "popular_videos",
            "featured_collections",
            "my_collections",
        }
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_valid: bool) -> None:
        config = PexelsSourceConfig(api_key="k", search_query=None)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source.validate_pexels_credentials",
            return_value=probe_result,
        ):
            valid, _ = self.source.validate_credentials(config, self.team_id)
        assert valid is expected_valid

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.pexels.com/v1/curated?per_page=80"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.pexels.com/videos/popular"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.pexels.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.pexels.com/v1/curated"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in self.source.get_non_retryable_errors())
