from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newyorktimes import (
    NewYorkTimesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.source import NewYorkTimesSource


def _config(api_key: str = "KEY", article_search_query: str | None = None) -> NewYorkTimesSourceConfig:
    return NewYorkTimesSourceConfig(api_key=api_key, article_search_query=article_search_query)


class TestNewYorkTimesSource:
    def setup_method(self) -> None:
        self.source = NewYorkTimesSource()
        self.team_id = 123

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs table list is safe.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["top_stories"])
        assert [s.name for s in schemas] == ["top_stories"]

    @pytest.mark.parametrize("valid", [True, False])
    def test_validate_credentials(self, valid: bool) -> None:
        with patch.object(source_module, "validate_nyt_credentials", return_value=valid):
            ok, error = self.source.validate_credentials(_config(), team_id=self.team_id)
        assert ok is valid
        assert (error is None) is valid

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

    def test_empty_query_becomes_none(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "article_search"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        captured: dict[str, Any] = {}

        with patch.object(source_module, "new_york_times_source", side_effect=lambda **kw: captured.update(kw)):
            self.source.source_for_pipeline(_config(article_search_query=""), MagicMock(), inputs)

        assert captured["query"] is None
