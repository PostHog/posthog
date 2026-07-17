from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewYorkTimesSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.new_york_times import (
    NewYorkTimesResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.source import NewYorkTimesSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "KEY", article_search_query: str | None = None) -> NewYorkTimesSourceConfig:
    return NewYorkTimesSourceConfig(api_key=api_key, article_search_query=article_search_query)


class TestNewYorkTimesSource:
    def setup_method(self) -> None:
        self.source = NewYorkTimesSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.NEWYORKTIMES

    def test_source_config_shape(self) -> None:
        config = self.source.get_source_config
        assert config.label == "New York Times"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/new-york-times"
        assert config.iconPath.endswith(".png")
        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"api_key", "article_search_query"}
        api_key_field = fields["api_key"]
        query_field = fields["article_search_query"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert isinstance(query_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert query_field.required is False

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs table list is safe.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert set(schemas) == set(ENDPOINTS)

    def test_only_article_search_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas["article_search"].supports_incremental is True
        assert [f["field"] for f in schemas["article_search"].incremental_fields] == ["pub_date"]
        for snapshot in ("most_popular_viewed", "most_popular_emailed", "most_popular_shared", "top_stories"):
            assert schemas[snapshot].supports_incremental is False
            assert schemas[snapshot].incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["top_stories"])
        assert [s.name for s in schemas] == ["top_stories"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(ENDPOINTS) <= names
        article_search = next(t for t in tables if t["name"] == "article_search")
        assert "Incremental" in article_search["sync_methods"]
        assert article_search["primary_keys"] == ["_id"]

    @pytest.mark.parametrize("valid", [True, False])
    def test_validate_credentials(self, valid: bool) -> None:
        with patch.object(source_module, "validate_nyt_credentials", return_value=valid):
            ok, error = self.source.validate_credentials(_config(), team_id=self.team_id)
        assert ok is valid
        assert (error is None) is valid

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is NewYorkTimesResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "article_search"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01"
        manager = MagicMock()
        captured: dict[str, Any] = {}

        sentinel = MagicMock()

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        with patch.object(source_module, "new_york_times_source", side_effect=fake_source):
            result = self.source.source_for_pipeline(_config(article_search_query="climate"), manager, inputs)

        assert result is sentinel
        assert captured["endpoint"] == "article_search"
        assert captured["query"] == "climate"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-06-01"

    def test_source_for_pipeline_drops_watermark_when_full_refresh(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "top_stories"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01"
        captured: dict[str, Any] = {}

        with patch.object(source_module, "new_york_times_source", side_effect=lambda **kw: captured.update(kw)):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None

    def test_empty_query_becomes_none(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "article_search"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        captured: dict[str, Any] = {}

        with patch.object(source_module, "new_york_times_source", side_effect=lambda **kw: captured.update(kw)):
            self.source.source_for_pipeline(_config(article_search_query=""), MagicMock(), inputs)

        assert captured["query"] is None
