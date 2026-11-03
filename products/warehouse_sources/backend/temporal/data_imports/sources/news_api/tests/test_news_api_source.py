from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
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

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

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

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"sources": []})]) as network:
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)
        assert [request.path for request in network.requests_log] == ["/v2/top-headlines/sources"]

    def test_validate_credentials_failure_message(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={"status": "error"})]) as network:
            valid, message = self.source.validate_credentials(_config(), self.team_id)
        assert valid is False
        assert message == "Invalid NewsAPI key"
        assert [request.path for request in network.requests_log] == ["/v2/top-headlines/sources"]

    def test_source_for_pipeline_plumbs_query_and_language(self) -> None:
        result = SourceDriver(self.source, _config(language="en")).run(
            "everything",
            [ScriptedResponse(json={"totalResults": 1, "articles": [{"url": "a"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-04T00:00:00",
        )

        assert result.raised is None
        assert result.paths == ["/v2/everything"]
        assert result.requests[0].param("q") == "bitcoin"
        assert result.requests[0].param("language") == "en"
        assert result.requests[0].param("from") == "2026-03-04T00:00:00"

    def test_empty_language_becomes_none(self) -> None:
        result = SourceDriver(self.source, _config(language="")).run(
            "everything", [ScriptedResponse(json={"totalResults": 1, "articles": [{"url": "a"}]})]
        )

        assert result.raised is None
        assert result.requests[0].param("language") is None
