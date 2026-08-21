from typing import Any

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newsapi import (
    NewsApiSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source import NewsApiSource


def _config(language: str | None = None) -> NewsApiSourceConfig:
    return NewsApiSourceConfig(api_key="k", query="bitcoin", language=language)


class TestNewsApiSource:
    def setup_method(self) -> None:
        self.source = NewsApiSource()
        self.team_id = 123

    def test_everything_incremental_field_is_published_at(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        fields = [f["field"] for f in schemas["everything"].incremental_fields]
        assert fields == ["publishedAt"]

    def test_validate_credentials_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source.validate_news_api_credentials",
            return_value=True,
        ):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure_message(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source.validate_news_api_credentials",
            return_value=False,
        ):
            valid, message = self.source.validate_credentials(_config(), self.team_id)
        assert valid is False
        assert message == "Invalid NewsAPI key"

    def test_source_for_pipeline_plumbs_query_and_language(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "everything"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00"

        captured: dict[str, Any] = {}
        sentinel = MagicMock()

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source.news_api_source",
            side_effect=fake_source,
        ):
            result = self.source.source_for_pipeline(_config(language="en"), MagicMock(), inputs)

        assert result is sentinel
        assert captured["endpoint"] == "everything"
        assert captured["query"] == "bitcoin"
        assert captured["language"] == "en"
        assert captured["db_incremental_field_last_value"] == "2026-03-04T00:00:00"

    def test_source_for_pipeline_drops_cursor_on_full_refresh(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "top_headlines"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00"

        captured: dict[str, Any] = {}

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source.news_api_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        # A full-refresh sync must not forward a stale watermark as `from`.
        assert captured["db_incremental_field_last_value"] is None

    def test_empty_language_becomes_none(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "everything"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        captured: dict[str, Any] = {}
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source.news_api_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(_config(language=""), MagicMock(), inputs)

        assert captured["language"] is None
