import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.source import WordpressSource


class TestWordpressSource:
    def setup_method(self):
        self.source = WordpressSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.site_url = "https://example.com"
        self.config.username = "admin"
        self.config.application_password = "app pass word"

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["site_url"]

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_exhausted_retryable_error_message_matches_retryable_error(self, status_code):
        # get_rows()'s fetch_page raises this once its own tenacity retry budget for a 429/5xx
        # response is exhausted. The status code and URL that follow are variable, so the
        # classifier must match on the stable prefix alone to keep this out of error tracking.
        raised = (
            f"WordPress API error (retryable): status={status_code}, url=https://example.com/wp-json/wp/v2/categories"
        )
        assert any(pattern.lower() in raised.lower() for pattern in self.source.get_retryable_errors())

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "posts"
