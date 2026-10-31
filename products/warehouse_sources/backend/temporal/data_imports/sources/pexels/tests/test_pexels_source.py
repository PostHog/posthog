from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pexels import PexelsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source import PexelsSource


class TestPexelsSource:
    def setup_method(self) -> None:
        self.source = PexelsSource()
        self.team_id = 123

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

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_valid: bool) -> None:
        config = PexelsSourceConfig(api_key="k", search_query=None)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source.validate_pexels_credentials",
            return_value=probe_result,
        ):
            valid, _ = self.source.validate_credentials(config, self.team_id)
        assert valid is expected_valid
