from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewsApiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.news_api import NewsApiResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source import NewsApiSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(language: str | None = None) -> NewsApiSourceConfig:
    return NewsApiSourceConfig(api_key="k", query="bitcoin", language=language)


class TestNewsApiSource:
    def setup_method(self) -> None:
        self.source = NewsApiSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.NEWSAPI

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand([("401 Client Error",), ("426 Client Error",)])
    def test_non_retryable_error_keys(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_source_config_required_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_key", "query", "language"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        assert fields["query"].required is True
        # The search query drives the article endpoints — a source with no query can't sync them.
        assert fields["language"].required is False

    @parameterized.expand(
        [
            ("everything", True),
            ("top_headlines", False),
            ("sources", False),
        ]
    )
    def test_schema_incremental_support(self, endpoint: str, expected_incremental: bool) -> None:
        # Only /v2/everything exposes a server-side date filter, so it's the only incremental table.
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].supports_append is expected_incremental

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["sources"])
        assert [s.name for s in schemas] == ["sources"]

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

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is NewsApiResumeConfig

    def test_source_for_pipeline_plumbs_query_and_language(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "everything"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-04T00:00:00"

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.source.news_api_source",
            side_effect=fake_source,
        ):
            result = self.source.source_for_pipeline(_config(language="en"), MagicMock(), inputs)

        assert result == "response"
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

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        schema_names = {s.name for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert schema_names <= set(canonical)
