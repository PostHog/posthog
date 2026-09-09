import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import ENDPOINTS
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

    def test_non_json_response_message_matches_non_retryable_error(self):
        # A 2xx non-JSON body surfaces as "Non-JSON response from <url>"; the classifier matches on
        # the stable prefix, so the variable URL must not stop it being recognised as non-retryable.
        errors = self.source.get_non_retryable_errors()
        raised = "Non-JSON response from https://example.com/wp-json/wp/v2/posts"
        matches = [friendly for key, friendly in errors.items() if key in raised]
        assert matches and matches[0] is not None

    def test_certificate_error_message_matches_non_retryable_error(self):
        # requests wraps a hostname/cert mismatch as an SSLError whose message embeds the
        # underlying CertificateError; the classifier matches on that class name, so the variable
        # hostname and cert names around it must not stop it being recognised as non-retryable.
        errors = self.source.get_non_retryable_errors()
        raised = (
            "HTTPSConnectionPool(host='example.com', port=443): Max retries exceeded with url: "
            "/wp-json/wp/v2/categories (Caused by SSLError(CertificateError(\"hostname 'example.com' "
            "doesn't match either of '*.example-host.test', 'example-host.test'\")))"
        )
        matches = [friendly for key, friendly in errors.items() if key in raised]
        assert matches and matches[0] is not None

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_exhausted_retryable_error_message_matches_retryable_error(self, status_code):
        # get_rows()'s fetch_page raises this once its own tenacity retry budget for a 429/5xx
        # response is exhausted. The status code and URL that follow are variable, so the
        # classifier must match on the stable prefix alone to keep this out of error tracking.
        raised = (
            f"WordPress API error (retryable): status={status_code}, url=https://example.com/wp-json/wp/v2/categories"
        )
        assert any(pattern.lower() in raised.lower() for pattern in self.source.get_retryable_errors())

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("posts", True),
            ("pages", True),
            ("comments", True),
            ("media", True),
            ("categories", False),
            ("tags", False),
            ("users", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    @pytest.mark.parametrize(
        "endpoint, fields",
        [
            ("posts", {"modified", "date"}),
            ("comments", {"date"}),
            ("categories", set()),
        ],
    )
    def test_advertised_incremental_fields(self, endpoint, fields):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert {f["field"] for f in schemas[endpoint].incremental_fields} == fields

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "posts"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
