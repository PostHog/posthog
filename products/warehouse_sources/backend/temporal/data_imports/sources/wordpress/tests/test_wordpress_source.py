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
