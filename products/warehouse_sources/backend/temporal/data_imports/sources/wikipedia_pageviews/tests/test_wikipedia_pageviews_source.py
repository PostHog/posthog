from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wikipediapageviews import (
    WikipediaPageviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ARTICLE_PAGEVIEWS_ENDPOINT,
    MAX_ARTICLES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.source import (
    WikipediaPageviewsSource,
)


class TestWikipediaPageviewsSource:
    def setup_method(self):
        self.source = WikipediaPageviewsSource()
        self.team_id = 123
        self.config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org")

    def test_validate_credentials_rejects_bad_start_date(self):
        config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org", start_date="not-a-date")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and "YYYY-MM-DD" in message

    def test_validate_credentials_rejects_too_many_articles(self):
        names = ",".join(f"Article_{i}" for i in range(MAX_ARTICLES + 1))
        config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org", article_names=names)
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message is not None and str(MAX_ARTICLES) in message

    def test_validate_credentials_rejects_article_schema_without_articles(self):
        is_valid, message = self.source.validate_credentials(
            self.config, self.team_id, schema_name=ARTICLE_PAGEVIEWS_ENDPOINT
        )
        assert is_valid is False
        assert message is not None and "article" in message.lower()

    def test_validate_credentials_plumbs_to_validate_project(self):
        with scripted_network([ScriptedResponse(json={"items": []})]) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert message is None
        assert len(network.requests_log) == 1
        assert "/pageviews/aggregate/en.wikipedia.org/all-access/user/daily/" in network.requests_log[0].path
