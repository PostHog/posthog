from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PexelsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.pexels import PexelsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source import PexelsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPexelsSource:
    def setup_method(self) -> None:
        self.source = PexelsSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PEXELS

    def test_config_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_key", "search_query"}
        api_key, search_query = fields["api_key"], fields["search_query"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(search_query, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert search_query.required is False

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

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock(spec=SourceInputs)
        inputs.logger = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PexelsResumeConfig

    def test_source_for_pipeline_plumbs_endpoint_and_query(self) -> None:
        config = PexelsSourceConfig(api_key="k", search_query="nature")
        inputs = mock.MagicMock(spec=SourceInputs)
        inputs.schema_name = "search_photos"
        inputs.logger = mock.MagicMock()
        manager = mock.MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pexels.source.pexels_source"
        ) as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "k"
        assert kwargs["endpoint"] == "search_photos"
        assert kwargs["search_query"] == "nature"
