import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.source import SalesforceSource


class TestSalesforceSourceNonRetryableErrors:
    def setup_method(self):
        self.source = SalesforceSource()

    @pytest.mark.parametrize(
        "error_message",
        [
            "Integration not found: 157911",
            "ValueError: Integration not found: 42",
        ],
    )
    def test_deleted_integration_is_non_retryable(self, error_message):
        # OAuthMixin.get_oauth_integration raises "Integration not found: <id>" when the linked
        # Salesforce integration was deleted. The id is volatile, so we match the stable prefix.
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    def test_unrelated_error_stays_retryable(self):
        error_message = "ConnectionError: Read timed out"

        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(pattern in error_message for pattern in non_retryable_errors), (
            f"'{error_message}' must not match a non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            "Tunnel connection failed: 502 Bad gateway",
            "Tunnel connection failed: 503 Service Unavailable",
            "Tunnel connection failed: 504 Gateway Timeout",
            "HTTPSConnectionPool(host='example.my.salesforce.com', port=443): Max retries exceeded "
            "with url: /services/oauth2/token (Caused by ProxyError('Cannot connect to proxy.', "
            "OSError('Tunnel connection failed: 502 Bad gateway')))",
        ],
    )
    def test_token_refresh_proxy_tunnel_failure_is_retryable(self, error_message):
        # salesforce_refresh_access_token builds its own tracked session, so a proxy CONNECT
        # failure during token refresh surfaces here as a bare OSError/ProxyError once
        # DEFAULT_RETRY's in-process attempts are exhausted. It's an egress-proxy blip Temporal's
        # activity retry recovers from, so it must stay out of error tracking as noise.
        retryable_errors = self.source.get_retryable_errors()

        assert any(pattern in error_message for pattern in retryable_errors), (
            f"Expected '{error_message}' to match a retryable pattern"
        )


class TestSalesforceSourceVersions:
    def setup_method(self):
        self.source = SalesforceSource()

    def test_new_sources_default_to_v67(self):
        # New sources (no pin) must be created on the current API version.
        assert self.source.default_version == "v67.0"
        assert self.source.resolve_api_version(None) == "v67.0"

    @pytest.mark.parametrize("version", ["v61.0", "v67.0"])
    def test_existing_pin_is_honored(self, version):
        # Pinned rows keep their version even after the default bump.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version
