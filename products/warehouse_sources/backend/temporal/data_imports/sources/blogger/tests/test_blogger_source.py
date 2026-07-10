from types import SimpleNamespace
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.blogger import BloggerResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.source import BloggerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "posts",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestBloggerSourceConfig:
    def test_source_type(self) -> None:
        assert BloggerSource().source_type == ExternalDataSourceType.BLOGGER

    def test_source_config_metadata(self) -> None:
        config = BloggerSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.BLOGGER
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/blogger"

    def test_source_config_fields(self) -> None:
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in BloggerSource().get_source_config.fields}
        assert set(fields) == {"api_key", "blog_id"}

        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True

        assert fields["blog_id"].type == SourceFieldInputConfigType.TEXT
        assert fields["blog_id"].required is True
        assert fields["blog_id"].secret is False


class TestBloggerSchemas:
    def test_get_schemas(self) -> None:
        schemas = {s.name: s for s in BloggerSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"blogs", "posts", "pages", "comments"}

        # Only posts/comments expose a server-side date filter, so only they are incremental.
        assert schemas["posts"].supports_incremental is True
        assert schemas["comments"].supports_incremental is True
        assert schemas["pages"].supports_incremental is False
        assert schemas["blogs"].supports_incremental is False

        assert [f["field"] for f in schemas["posts"].incremental_fields] == ["published"]
        assert schemas["pages"].incremental_fields == []
        for schema in schemas.values():
            assert schema.detected_primary_keys == ["id"]

    def test_get_schemas_names_filter(self) -> None:
        schemas = BloggerSource().get_schemas(MagicMock(), team_id=1, names=["posts"])
        assert [s.name for s in schemas] == ["posts"]

    def test_lists_tables_without_credentials(self) -> None:
        assert BloggerSource.lists_tables_without_credentials is True

    def test_documented_tables_render_with_canonical_descriptions(self) -> None:
        tables = {t["name"]: t for t in BloggerSource().get_documented_tables()}
        assert set(tables) == {"blogs", "posts", "pages", "comments"}
        assert "Incremental" in tables["posts"]["sync_methods"]
        assert "Incremental" not in tables["pages"]["sync_methods"]
        # Description comes from canonical_descriptions.py.
        assert tables["posts"]["description"]

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = BloggerSource().get_canonical_descriptions()
        assert set(descriptions) == {"blogs", "posts", "pages", "comments"}
        assert "id" in descriptions["posts"]["columns"]


class TestBloggerCredentials:
    def test_validate_credentials_delegates_to_transport(self) -> None:
        config = SimpleNamespace(api_key="K", blog_id="BID")
        with patch.object(source_module, "validate_blogger_credentials", return_value=(True, None)) as mock_validate:
            result = BloggerSource().validate_credentials(config, team_id=1)  # type: ignore[arg-type]
        assert result == (True, None)
        mock_validate.assert_called_once_with("K", "BID")

    def test_validate_credentials_propagates_failure(self) -> None:
        config = SimpleNamespace(api_key="K", blog_id="BID")
        with patch.object(source_module, "validate_blogger_credentials", return_value=(False, "nope")):
            result = BloggerSource().validate_credentials(config, team_id=1)  # type: ignore[arg-type]
        assert result == (False, "nope")

    @parameterized.expand(
        [
            (
                "bad_request",
                "400 Client Error: Bad Request for url: https://www.googleapis.com/blogger/v3/blogs/1/posts",
            ),
            ("unauthorized", "401 Client Error: Unauthorized for url: https://www.googleapis.com/blogger/v3/blogs/1"),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://www.googleapis.com/blogger/v3/blogs/1/comments",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = BloggerSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://www.googleapis.com/blogger/v3/blogs/1/posts",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='www.googleapis.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = BloggerSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestBloggerPipelinePlumbing:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = BloggerSource().get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BloggerResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        config = SimpleNamespace(api_key="K", blog_id="BID")
        inputs = _make_inputs(
            schema_name="comments",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="published",
        )
        with patch.object(source_module, "blogger_source", fake_source):
            BloggerSource().source_for_pipeline(config, MagicMock(), inputs)  # type: ignore[arg-type]

        assert captured["api_key"] == "K"
        assert captured["blog_id"] == "BID"
        assert captured["endpoint"] == "comments"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert captured["incremental_field"] == "published"

    def test_source_for_pipeline_clears_last_value_when_not_incremental(self) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        config = SimpleNamespace(api_key="K", blog_id="BID")
        inputs = _make_inputs(
            schema_name="posts",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        with patch.object(source_module, "blogger_source", fake_source):
            BloggerSource().source_for_pipeline(config, MagicMock(), inputs)  # type: ignore[arg-type]

        # When the run isn't incremental, the stale watermark must not leak through as a startDate.
        assert captured["db_incremental_field_last_value"] is None
