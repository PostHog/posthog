from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.source import NewsDataSource


class TestGetSchemas:
    @parameterized.expand(
        [
            # Only the date-filter endpoints expose a real server-side timestamp filter, so only they
            # can sync incrementally. latest/sources are full refresh.
            ("latest", False),
            ("archive", True),
            ("crypto", True),
            ("sources", False),
        ]
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected_incremental: bool) -> None:
        schemas = {s.name: s for s in NewsDataSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].supports_append is expected_incremental

    def test_incremental_endpoints_advertise_pubdate(self) -> None:
        schemas = {s.name: s for s in NewsDataSource().get_schemas(MagicMock(), team_id=1)}
        assert [f["field"] for f in schemas["archive"].incremental_fields] == ["pubDate"]

    def test_names_filter(self) -> None:
        schemas = NewsDataSource().get_schemas(MagicMock(), team_id=1, names=["crypto"])
        assert [s.name for s in schemas] == ["crypto"]
