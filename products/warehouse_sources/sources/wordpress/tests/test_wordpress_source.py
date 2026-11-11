import pytest
from unittest import mock

from products.warehouse_sources.sources.wordpress.source import WordpressSource


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

    def test_tls_certificate_verify_failure_matches_non_retryable_error(self):
        # requests/urllib3's own message for a site whose TLS certificate fails chain-of-trust
        # verification (self-signed, expired, untrusted CA). get_rows()'s retry on
        # requests.exceptions.ConnectionError (SSLError's base class) exhausts without ever
        # succeeding, since the site's certificate doesn't change between attempts. The host and
        # path that follow are variable, so the classifier must match on the stable OpenSSL error
        # code alone to keep this out of error tracking.
        raised = (
            "HTTPSConnectionPool(host='example.com', port=443): Max retries exceeded with "
            "url: /wp-json/wp/v2/tags?per_page=100&orderby=id&order=asc (Caused by "
            "SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate "
            "verify failed: self-signed certificate (_ssl.c:1082)')))"
        )
        assert any(pattern.lower() in raised.lower() for pattern in self.source.get_non_retryable_errors())
