from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.newsdata import NewsDataResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.source import NewsDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _source_inputs(**overrides: Any) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = overrides.get("schema_name", "archive")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2024-01-15 00:00:00")
    return inputs


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert NewsDataSource().source_type == ExternalDataSourceType.NEWSDATA

    def test_config_identity_and_release_contract(self) -> None:
        config = NewsDataSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.NEWS_DATA
        # Alpha but released: the finished source must be reachable, so unreleasedSource stays off.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        # The doc slug is derived from this URL; a mismatch 404s the docs page.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/newsdata"

    def test_api_key_is_a_required_secret_field(self) -> None:
        fields = NewsDataSource().get_source_config.fields
        api_key_fields = [f for f in fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key"]
        assert len(api_key_fields) == 1
        field = api_key_fields[0]
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True


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


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://newsdata.io/api/1/archive?from_date=2024-01-01",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://newsdata.io/api/1/crypto"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        assert any(key in observed for key in NewsDataSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='newsdata.io', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://newsdata.io/api/1/latest"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://newsdata.io/api/1/latest"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed: str) -> None:
        assert not any(key in observed for key in NewsDataSource().get_non_retryable_errors())


class TestSourceForPipeline:
    def test_passes_watermark_only_when_incremental(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.source.newsdata_source"
        ) as mock_source:
            NewsDataSource().source_for_pipeline(
                config=MagicMock(api_key="pub_test"),
                resumable_source_manager=MagicMock(),
                inputs=_source_inputs(schema_name="archive", should_use_incremental_field=True),
            )
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pub_test"
        assert kwargs["endpoint"] == "archive"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-15 00:00:00"

    def test_watermark_dropped_on_full_refresh(self) -> None:
        # On a full-refresh run the stored watermark must not leak into the query, or an unwanted
        # from_date filter would silently truncate the pull.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.source.newsdata_source"
        ) as mock_source:
            NewsDataSource().source_for_pipeline(
                config=MagicMock(api_key="pub_test"),
                resumable_source_manager=MagicMock(),
                inputs=_source_inputs(schema_name="latest", should_use_incremental_field=False),
            )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = NewsDataSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is NewsDataResumeConfig


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the public docs Supported tables section renders.
        source = NewsDataSource()
        assert source.lists_tables_without_credentials is True
        table_names = {t["name"] for t in source.get_documented_tables()}
        assert {"latest", "archive", "crypto", "sources"}.issubset(table_names)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = NewsDataSource().get_canonical_descriptions()
        assert {"latest", "archive", "crypto", "sources"}.issubset(descriptions.keys())
