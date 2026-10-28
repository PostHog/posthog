from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wikipediapageviews import (
    WikipediaPageviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ARTICLE_PAGEVIEWS_ENDPOINT,
    COUNTRY_TOP_ARTICLES_ENDPOINT,
    MAX_ARTICLES,
    MAX_COUNTRIES,
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

    @parameterized.expand(
        [
            ("schema_without_countries", None, COUNTRY_TOP_ARTICLES_ENDPOINT, "country codes"),
            ("not_two_letters", "US, FRA, 1", None, "FRA, 1"),
            (
                "too_many",
                ",".join(f"{chr(65 + i)}{chr(65 + i)}" for i in range(MAX_COUNTRIES + 1)),
                None,
                str(MAX_COUNTRIES),
            ),
        ]
    )
    def test_validate_credentials_rejects_bad_countries(self, _name, countries, schema_name, expected_in_message):
        config = WikipediaPageviewsSourceConfig(project="en.wikipedia.org", countries=countries)
        with scripted_network([]) as network:
            is_valid, message = self.source.validate_credentials(config, self.team_id, schema_name=schema_name)
        assert is_valid is False
        assert message is not None and expected_in_message in message
        assert network.requests_log == []

    def test_validate_credentials_plumbs_to_validate_project(self):
        with scripted_network([ScriptedResponse(json={"items": []})]) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert message is None
        assert len(network.requests_log) == 1
        assert "/pageviews/aggregate/en.wikipedia.org/all-access/user/daily/" in network.requests_log[0].path
