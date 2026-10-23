import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newyorktimes import (
    NewYorkTimesSourceConfig,
)
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

    @pytest.mark.parametrize("valid", [True, False])
    def test_validate_credentials(self, valid: bool) -> None:
        status = 200 if valid else 401
        with scripted_network([ScriptedResponse(status=status)]):
            ok, error = self.source.validate_credentials(_config(), team_id=self.team_id)
        assert ok is valid
        assert (error is None) is valid

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, _config(article_search_query="climate")).run(
            "article_search",
            [ScriptedResponse(json={"response": {"docs": []}})],
            incremental_field="pub_date",
            db_incremental_field_last_value="2026-06-01",
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "article_search"
        assert result.paths == ["/svc/search/v2/articlesearch.json"]
        assert result.params("q") == ["climate"]
        assert result.params("begin_date") == ["2026-06-01"]

    def test_empty_query_becomes_none(self) -> None:
        result = SourceDriver(self.source, _config(article_search_query="")).run(
            "article_search", [ScriptedResponse(json={"response": {"docs": []}})]
        )

        assert result.raised is None
        assert result.params("q") == [None]
